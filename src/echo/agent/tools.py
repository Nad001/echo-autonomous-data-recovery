from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

from echo.compare import amount_mismatches, field_mismatches, load_dest_map, load_source_map
from echo.config import SAMPLE_LIMIT
from echo.ingest.contract import is_agent_forbidden
from echo.recovery.planner import build_plan
from echo.sim.transforms import effective_multiplier

ToolFn = Callable[..., dict]


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def refuse_filesystem(path: str) -> None:
    from pathlib import Path

    if is_agent_forbidden(Path(path)):
        raise PermissionError("Agent is not allowed to read evaluation or scenario patch files")


OPENAI_TOOLS = [
    {
        "type": "function",
        "name": "inspect_incident",
        "description": "Return the persisted monitoring alert for this incident.",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "inspect_sync_run",
        "description": "Return execution/integrity status, transform version, and batch integrity summary for a run.",
        "parameters": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "inspect_sync_logs",
        "description": "Return compact synchronization and integrity logs for a run.",
        "parameters": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "compare_records",
        "description": "Compare supported source and destination fields. Returns counts, ratio histogram, and a small sample.",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "profile_column",
        "description": "Numeric profile of amount_halalas on source and destination.",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "profile_text",
        "description": "Compare corrupted text fields using lengths, truncation, character changes, and bounded source/destination examples.",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "inspect_pipeline_configuration",
        "description": "Return current pipeline transform version, effective multiplier, quarantine status, and trust flags.",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "inspect_record_history",
        "description": "Return destination audit, source trust, and recent field history for up to 20 record ids.",
        "parameters": {
            "type": "object",
            "properties": {"record_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["record_ids"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "profile_fields",
        "description": "Profile the actual fields present in the supported source and destination schemas and summarize discrepancy types without assuming a domain.",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "test_hypothesis",
        "description": "Run a named Python check appropriate to the observed field type: amount_scale, text_truncation, text_replacement, text_encoding, missing_keys, dest_modified, transform_mismatch.",
        "parameters": {
            "type": "object",
            "properties": {
                "hypothesis": {
                    "type": "string",
                    "enum": ["amount_scale", "text_truncation", "text_replacement", "text_encoding", "missing_keys", "dest_modified", "transform_mismatch"],
                }
            },
            "required": ["hypothesis"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "propose_recovery",
        "description": "Build a deterministic dry-run repair plan from trusted source amounts. Does not execute changes.",
        "parameters": {
            "type": "object",
            "properties": {"record_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["record_ids"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "submit_investigation",
        "description": "Submit the final investigation outcome. This ends the loop. Do not invent amounts.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "observed_issue": {"type": "string"},
                "suspected_root_cause": {"type": "string"},
                "supporting_evidence": {"type": "array", "items": {"type": "string"}},
                "suspected_cause": {"type": "string"},
                "confidence": {"type": ["number", "null"]},
                "safety_concerns": {"type": "array", "items": {"type": "string"}},
                "human_review_reason": {"type": ["string", "null"]},
                "affected_record_ids": {"type": "array", "items": {"type": "string"}},
                "earliest_batch_id": {"type": ["string", "null"]},
                "pipeline_safe_to_retry": {"type": "boolean"},
                "escalate": {"type": "boolean"},
                "uncertainty": {"type": "array", "items": {"type": "string"}},
                "strategy": {
                    "type": "string",
                    "enum": ["restore", "quarantine_and_restore", "escalate"],
                },
                "finding_summary": {"type": "string"},
                "evidence_summary": {"type": "string"},
                "recommended_action": {"type": "string"},
            },
            "required": [
                "title",
                "summary",
                "observed_issue",
                "suspected_root_cause",
                "supporting_evidence",
                "suspected_cause",
                "confidence",
                "affected_record_ids",
                "earliest_batch_id",
                "pipeline_safe_to_retry",
                "escalate",
                "uncertainty",
                "strategy",
                "safety_concerns",
                "human_review_reason",
                "finding_summary",
                "evidence_summary",
                "recommended_action",
            ],
            "additionalProperties": False,
        },
    },
]

# Strict schemas keep diagnostic arguments and the final report machine-valid.
for _tool in OPENAI_TOOLS:
    _tool.setdefault("strict", True)


class ToolContext:
    def __init__(
        self,
        finance: sqlite3.Connection,
        analytics: sqlite3.Connection,
        echo: sqlite3.Connection,
        incident_id: str,
    ) -> None:
        self.finance = finance
        self.analytics = analytics
        self.echo = echo
        self.incident_id = incident_id
        self.cache: dict[str, dict] = {}
        self.final: dict | None = None

    def record_event(self, kind: str, summary: str, payload: dict) -> None:
        self.echo.execute(
            "INSERT INTO investigation_events(incident_id, ts, kind, summary, payload_json) VALUES (?,?,?,?,?)",
            (self.incident_id, _utcnow(), kind, summary, json.dumps(payload)),
        )
        self.echo.commit()


def _sample(rows: list[dict], limit: int = SAMPLE_LIMIT) -> list[dict]:
    return rows[:limit]


def _schema_snapshot(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [
        {"name": row["name"], "type": row["type"], "nullable": not bool(row["notnull"])}
        for row in conn.execute(f"PRAGMA table_info({table})")
    ]


def _field_type(field: str | None) -> str:
    if field in {"amount_halalas", "amount", "value", "quantity", "count"}:
        return "numeric"
    if field in {"record", "record_id"}:
        return "identifier"
    return "text_or_other"


def build_evidence_package(ctx: ToolContext) -> dict[str, Any]:
    """Build bounded, scenario-independent evidence for the investigator."""
    mismatches = field_mismatches(ctx.finance, ctx.analytics)
    source_count = ctx.finance.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"]
    destination_count = ctx.analytics.execute("SELECT COUNT(*) AS n FROM fact_transactions").fetchone()["n"]
    fields = sorted({row.get("field") for row in mismatches if row.get("field")})
    examples = [
        {
            "record_id": row["record_id"],
            "field": row.get("field"),
            "field_type": _field_type(row.get("field")),
            "source_value": row.get("source_value"),
            "destination_value": row.get("dest_value"),
            "ratio": row.get("ratio"),
            "destination_version": row.get("dest_version"),
            "text_change_type": _text_change_type(row.get("source_value"), row.get("dest_value")) if isinstance(row.get("source_value"), str) else None,
        }
        for row in _sample(mismatches, 5)
    ]
    return {
        "schema": {
            "source": {"table": "transactions", "fields": _schema_snapshot(ctx.finance, "transactions")},
            "destination": {"table": "fact_transactions", "fields": _schema_snapshot(ctx.analytics, "fact_transactions")},
        },
        "scope": {"source_records": source_count, "destination_records": destination_count, "compared_records": min(source_count, destination_count)},
        "discrepancies": {
            "count": len(mismatches),
            "affected_record_count": len({row["record_id"] for row in mismatches}),
            "fields": fields,
            "field_types": {field: _field_type(field) for field in fields},
            "examples": examples,
        },
        "diagnostics": {"available": ["compare_records", "profile_fields", "profile_column", "profile_text", "inspect_record_history", "test_hypothesis"]},
    }


def _text_change_type(source: str | None, destination: str | None) -> str:
    source = source or ""
    destination = destination or ""
    if len(destination) < len(source) and source.startswith(destination):
        return "truncation"
    if len(destination) < len(source):
        # A bounded subsequence check catches interior character loss without
        # assuming a particular fixture string or hidden scenario answer.
        iterator = iter(source)
        if all(character in iterator for character in destination):
            return "partial_character_loss"
    if sorted(source.replace(" ", "").lower()) == sorted(destination.replace(" ", "").lower()) and source != destination:
        return "scrambled_characters"
    if "�" in destination or "Ã" in destination or "Â" in destination:
        return "encoding_or_decoding"
    return "replacement_or_transformation"


def inspect_incident(ctx: ToolContext) -> dict:
    row = ctx.echo.execute("SELECT alert_json, severity, run_id, pipeline_id, investigation_status FROM incidents WHERE id=?", (ctx.incident_id,)).fetchone()
    if row is None:
        return {"error": "incident not found"}
    alert = json.loads(row["alert_json"])
    observed = field_mismatches(ctx.finance, ctx.analytics)
    return {
        "incident_id": ctx.incident_id,
        "severity": row["severity"],
        "run_id": row["run_id"],
        "pipeline_id": row["pipeline_id"],
        "investigation_status": row["investigation_status"],
        "alert": alert,
        "observed_discrepancy_count": len(observed),
        "observed_fields": sorted({row.get("field") for row in observed if row.get("field")}),
        "observed_examples": [
            {"record_id": row["record_id"], "field": row.get("field"), "source_value": row.get("source_value"), "destination_value": row.get("dest_value")}
            for row in _sample(observed, 5)
        ],
    }


def inspect_sync_run(ctx: ToolContext, run_id: str) -> dict:
    run = ctx.echo.execute("SELECT * FROM sync_runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        return {"error": "run not found"}
    batches = [dict(b) for b in ctx.echo.execute("SELECT id, batch_seq, integrity_status, record_count FROM sync_batches WHERE run_id=? ORDER BY batch_seq", (run_id,))]
    earliest = next((b["id"] for b in batches if b["integrity_status"] == "corrupted"), None)
    return {
        "run": dict(run),
        "batches": batches,
        "earliest_corrupted_batch_id": earliest,
        "note": "execution_status and integrity_status are independent",
    }


def inspect_sync_logs(ctx: ToolContext, run_id: str) -> dict:
    logs = [dict(r) for r in ctx.echo.execute("SELECT id, ts, level, message FROM sync_logs WHERE run_id=? ORDER BY ts", (run_id,))]
    return {"run_id": run_id, "logs": logs[-30:]}


def compare_records(ctx: ToolContext) -> dict:
    mismatches = field_mismatches(ctx.finance, ctx.analytics)
    ratios = Counter()
    for row in mismatches:
        if row.get("ratio") is None:
            continue
        ratio = row["ratio"]
        if abs(ratio - 100) < 0.01:
            ratios["100"] += 1
        elif abs(ratio - 1000) < 0.01:
            ratios["1000"] += 1
        else:
            ratios["other"] += 1
    sample = [
        {
            "record_id": row["record_id"],
            "field": row.get("field"),
            "source_value": row.get("source_value"),
            "dest_value": row.get("dest_value"),
            "ratio": row.get("ratio"),
            "dest_version": row.get("dest_version"),
            "text_change_type": _text_change_type(row.get("source_value"), row.get("dest_value")) if row.get("field") == "description" else None,
        }
        for row in _sample(mismatches, 5)
    ]
    return {
        "mismatch_count": len(mismatches),
        "ratio_histogram": dict(ratios),
        "sample": sample,
        "affected_record_ids_sample": [row["record_id"] for row in _sample(mismatches, 5)],
        "affected_record_ids_all_count": len(mismatches),
        "affected_record_ids": [row["record_id"] for row in mismatches[:500]],
        "fields": sorted({row.get("field") for row in mismatches if row.get("field")}),
        "field_types": {_field: _field_type(_field) for _field in sorted({row.get("field") for row in mismatches if row.get("field")})},
        "evidence_summary": {
            "scope": build_evidence_package(ctx)["scope"],
            "discrepancy_count": len(mismatches),
            "fields": sorted({row.get("field") for row in mismatches if row.get("field")}),
        },
    }


def profile_fields(ctx: ToolContext) -> dict:
    package = build_evidence_package(ctx)
    return {
        "schema": package["schema"],
        "scope": package["scope"],
        "fields": package["discrepancies"]["fields"],
        "field_types": package["discrepancies"]["field_types"],
        "discrepancy_count": package["discrepancies"]["count"],
    }


def profile_column(ctx: ToolContext) -> dict:
    def stats(conn: sqlite3.Connection, table: str) -> dict:
        row = conn.execute(f"SELECT COUNT(*) n, MIN(amount_halalas) mn, MAX(amount_halalas) mx, AVG(amount_halalas) av FROM {table}").fetchone()
        return {"count": row["n"], "min": row["mn"], "max": row["mx"], "avg": row["av"]}

    return {"source": stats(ctx.finance, "transactions"), "destination": stats(ctx.analytics, "fact_transactions")}


def profile_text(ctx: ToolContext) -> dict:
    mismatches = [row for row in field_mismatches(ctx.finance, ctx.analytics) if row.get("field") == "description"]
    changes = Counter(_text_change_type(row.get("source_value"), row.get("dest_value")) for row in mismatches)
    examples = [
        {
            "record_id": row["record_id"],
            "field": "description",
            "change_type": _text_change_type(row.get("source_value"), row.get("dest_value")),
            "source_length": len(row.get("source_value") or ""),
            "destination_length": len(row.get("dest_value") or ""),
            "source_value": row.get("source_value"),
            "destination_value": row.get("dest_value"),
        }
        for row in _sample(mismatches, 5)
    ]
    return {"text_mismatch_count": len(mismatches), "change_type_counts": dict(changes), "examples": examples}


def inspect_pipeline_configuration(ctx: ToolContext) -> dict:
    pipeline = ctx.echo.execute("SELECT * FROM pipelines WHERE id=(SELECT pipeline_id FROM incidents WHERE id=?)", (ctx.incident_id,)).fetchone()
    if pipeline is None:
        return {"error": "pipeline not found"}
    versions = [dict(v) for v in ctx.echo.execute("SELECT id, name, is_trusted FROM transform_versions WHERE pipeline_id=?", (pipeline["id"],))]
    multiplier, version_id, faulty = effective_multiplier(ctx.echo, pipeline["id"])
    return {
        "pipeline_id": pipeline["id"],
        "status": pipeline["status"],
        "current_transform_version": version_id,
        "effective_amount_multiplier": multiplier,
        "config_override": json.loads(pipeline["config_override_json"] or "{}"),
        "remains_faulty": bool(pipeline["remains_faulty"]),
        "versions": versions,
    }


def inspect_record_history(ctx: ToolContext, record_ids: list[str]) -> dict:
    ids = record_ids[:SAMPLE_LIMIT]
    out = []
    for record_id in ids:
        trust = ctx.echo.execute("SELECT trust_state, reason FROM source_trust WHERE record_id=?", (record_id,)).fetchone()
        audits = [dict(r) for r in ctx.echo.execute("SELECT ts, actor, change_type FROM dest_audit WHERE record_id=?", (record_id,))]
        history = [dict(r) for r in ctx.echo.execute("SELECT ts, system, field, old_value, new_value, note FROM record_history WHERE record_id=? ORDER BY id DESC LIMIT 5", (record_id,))]
        src = ctx.finance.execute("SELECT amount_halalas, source_version FROM transactions WHERE record_id=?", (record_id,)).fetchone()
        dst = ctx.analytics.execute("SELECT amount_halalas, dest_version FROM fact_transactions WHERE record_id=?", (record_id,)).fetchone()
        out.append(
            {
                "record_id": record_id,
                "source": dict(src) if src else None,
                "destination": dict(dst) if dst else None,
                "source_trust": dict(trust) if trust else {"trust_state": "available"},
                "destination_audit": audits,
                "history": history,
            }
        )
    return {"records": out}


def test_hypothesis(ctx: ToolContext, hypothesis: str) -> dict:
    mismatches = field_mismatches(ctx.finance, ctx.analytics)
    if hypothesis == "amount_scale":
        ratios = Counter()
        for row in mismatches:
            if row.get("ratio") in (100, 100.0):
                ratios[100] += 1
            elif row.get("ratio") in (1000, 1000.0):
                ratios[1000] += 1
        dominant = None
        if ratios:
            dominant = max(ratios, key=ratios.get)
        return {"hypothesis": hypothesis, "supported": bool(dominant), "dominant_factor": dominant, "counts": {str(k): v for k, v in ratios.items()}}
    if hypothesis in {"text_truncation", "text_replacement", "text_encoding"}:
        mismatches = [row for row in mismatches if row.get("field") == "description"]
        wanted = {
            "text_truncation": "truncation",
            "text_replacement": "replacement_or_transformation",
            "text_encoding": "encoding_or_decoding",
        }[hypothesis]
        matches = [row for row in mismatches if _text_change_type(row.get("source_value"), row.get("dest_value")) == wanted]
        return {"hypothesis": hypothesis, "supported": bool(matches), "matching_records": len(matches), "text_mismatch_count": len(mismatches)}
    if hypothesis == "missing_keys":
        src = set(load_source_map(ctx.finance))
        dst = set(load_dest_map(ctx.analytics))
        return {"hypothesis": hypothesis, "supported": bool(src - dst), "missing_in_destination": len(src - dst)}
    if hypothesis == "dest_modified":
        audits = ctx.echo.execute("SELECT COUNT(*) n FROM dest_audit").fetchone()["n"]
        bumped = ctx.analytics.execute("SELECT COUNT(*) n FROM fact_transactions WHERE dest_version > 1").fetchone()["n"]
        return {"hypothesis": hypothesis, "supported": audits > 0 or bumped > 0, "audit_rows": audits, "dest_version_gt_1": bumped}
    if hypothesis == "transform_mismatch":
        incident = ctx.echo.execute("SELECT pipeline_id FROM incidents WHERE id=?", (ctx.incident_id,)).fetchone()
        multiplier, version_id, faulty = effective_multiplier(ctx.echo, incident["pipeline_id"])
        return {
            "hypothesis": hypothesis,
            "supported": multiplier != 1 or faulty,
            "effective_amount_multiplier": multiplier,
            "version_id": version_id,
            "remains_faulty": faulty,
        }
    return {"error": "unsupported hypothesis"}


def propose_recovery(ctx: ToolContext, record_ids: list[str] | None = None) -> dict:
    incident = ctx.echo.execute("SELECT pipeline_id FROM incidents WHERE id=?", (ctx.incident_id,)).fetchone()
    plan = build_plan(
        ctx.finance,
        ctx.analytics,
        ctx.echo,
        incident_id=ctx.incident_id,
        pipeline_id=incident["pipeline_id"],
        requested_ids=record_ids,
    )
    compact_items = [
        {
            "record_id": item["record_id"],
            "field": item["field"],
            "current_value": item["current_value"],
            "proposed_value": item["proposed_value"],
            "safety_status": item["safety_status"],
            "reason": item["reason"],
        }
        for item in plan["items"][:SAMPLE_LIMIT]
    ]
    return {
        "decision": plan["decision"],
        "pipeline_faulty": plan["pipeline_faulty"],
        "safe_count": plan["safe_count"],
        "unsafe_count": plan["unsafe_count"],
        "mismatch_count": plan["mismatch_count"],
        "item_sample": compact_items,
    }


def submit_investigation(ctx: ToolContext, **payload: Any) -> dict:
    required = {
        "title", "summary", "observed_issue", "suspected_root_cause", "supporting_evidence",
        "suspected_cause", "confidence", "affected_record_ids", "pipeline_safe_to_retry",
        "escalate", "strategy", "safety_concerns", "human_review_reason", "finding_summary",
        "evidence_summary", "recommended_action",
    }
    missing = sorted(required - payload.keys())
    confidence = payload.get("confidence")
    valid_confidence = confidence is None or (isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and math.isfinite(float(confidence)) and 0 <= float(confidence) <= 1)
    valid_report = all(isinstance(payload.get(key), str) and payload.get(key).strip() for key in ("title", "summary", "observed_issue", "suspected_root_cause", "finding_summary", "evidence_summary", "recommended_action"))
    valid_lists = all(isinstance(payload.get(key), list) and all(isinstance(item, str) for item in payload.get(key)) for key in ("supporting_evidence", "safety_concerns", "affected_record_ids", "uncertainty"))
    if missing or not valid_confidence or not valid_report or not valid_lists or payload.get("strategy") not in {"restore", "quarantine_and_restore", "escalate"}:
        return {
            "accepted": False,
            "error": "invalid_investigation_response",
            "missing": missing,
            "confidence_valid": valid_confidence,
            "report_valid": valid_report and valid_lists,
            "strategy_valid": payload.get("strategy") in {"restore", "quarantine_and_restore", "escalate"},
        }
    ctx.final = payload
    return {"accepted": True}


DISPATCH: dict[str, ToolFn] = {
    "inspect_incident": inspect_incident,
    "inspect_sync_run": inspect_sync_run,
    "inspect_sync_logs": inspect_sync_logs,
    "compare_records": compare_records,
    "profile_fields": profile_fields,
    "profile_column": profile_column,
    "profile_text": profile_text,
    "inspect_pipeline_configuration": inspect_pipeline_configuration,
    "inspect_record_history": inspect_record_history,
    "test_hypothesis": test_hypothesis,
    "propose_recovery": propose_recovery,
    "submit_investigation": submit_investigation,
}


def execute_tool(ctx: ToolContext, name: str, arguments: dict) -> dict:
    if name not in DISPATCH:
        return {"error": f"unknown tool {name}"}
    result = DISPATCH[name](ctx, **(arguments or {}))
    ctx.record_event("tool_executed", f"{name}", {"tool": name, "arguments": arguments, "result_preview": _preview(result)})
    return result


def _preview(result: dict) -> dict:
    raw = json.dumps(result)
    if len(raw) < 2000:
        return result
    cloned = dict(result)
    if "affected_record_ids" in cloned and isinstance(cloned["affected_record_ids"], list):
        cloned["affected_record_ids"] = cloned["affected_record_ids"][:SAMPLE_LIMIT]
        cloned["affected_record_ids_truncated"] = True
    if "items" in cloned:
        cloned["items"] = "truncated"
    return cloned
