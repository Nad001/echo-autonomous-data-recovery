from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from echo.config import PACKAGE_DIR, PIPELINE_ID
from echo.db.connections import analytics_conn, echo_conn, finance_conn, reset_runtime_files
from echo.ingest.importer import import_baseline, load_history, load_transform_versions
from echo.sim.monitor import assess_integrity, create_incident_from_monitor
from echo.sim.runner import run_sync

BATCH_SIZE = 500


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _record_batch_seq(record_id: str) -> int:
    numeric = int(record_id.split("-")[1])
    return ((numeric - 1) // BATCH_SIZE) + 1


def _load_patch(case_id: str) -> dict:
    registry_path = PACKAGE_DIR / "scenario_registry.json"
    registry = json.loads(registry_path.read_text())
    entries = {item["case_id"]: item for item in registry.get("active_scenarios", [])}
    if case_id not in entries:
        raise ValueError(f"Unknown active scenario: {case_id}")
    path = PACKAGE_DIR / entries[case_id]["patch_path"]
    if not path.is_file():
        raise FileNotFoundError(f"Missing scenario patch for {case_id}")
    return json.loads(path.read_text())


def active_scenario_ids() -> list[str]:
    registry = json.loads((PACKAGE_DIR / "scenario_registry.json").read_text())
    return [item["case_id"] for item in registry.get("active_scenarios", [])]


def _apply_destination_mutations(analytics: sqlite3.Connection, echo: sqlite3.Connection, patch: dict) -> None:
    for mutation in patch.get("destination_mutations") or []:
        record_ids = mutation.get("record_ids") or ([mutation["record_id"]] if mutation.get("record_id") else [])
        field = mutation["field"]
        operation = mutation["operation"]
        if operation in {"multiply_all", "set_all"}:
            record_ids = [row["record_id"] for row in analytics.execute("SELECT record_id FROM fact_transactions")]
        if field not in {"amount_halalas", "description", "dest_version"}:
            raise ValueError(f"Unsupported scenario mutation field: {field}")
        for record_id in record_ids:
            row = analytics.execute("SELECT amount_halalas, description, dest_version FROM fact_transactions WHERE record_id=?", (record_id,)).fetchone()
            if row is None:
                continue
            if operation in {"multiply", "multiply_all"} and field == "amount_halalas":
                old = int(row["amount_halalas"])
                value = old * int(mutation["factor"])
            elif operation in {"set", "set_all"}:
                old = row[field]
                value = int(mutation["value"]) if field == "dest_version" else mutation["value"]
            else:
                raise ValueError(f"Unsupported scenario mutation operation: {operation}")
            analytics.execute(f"UPDATE fact_transactions SET {field}=? WHERE record_id=?", (value, record_id))
            echo.execute(
                "INSERT INTO record_history(record_id, ts, system, field, old_value, new_value, note) VALUES (?,?,?,?,?,?,?)",
                (record_id, _utcnow(), "analytics", field, str(old), str(value), mutation.get("note") or operation),
            )


def _apply_pipeline_mutations(echo: sqlite3.Connection, patch: dict) -> None:
    for mutation in patch.get("pipeline_mutations") or []:
        if mutation.get("type") != "set_transform":
            continue
        version_id = mutation["transform_version_id"]
        override = mutation.get("configuration_override") or {}
        remains = 1 if mutation.get("remains_active") else 0
        echo.execute(
            """
            UPDATE pipelines
            SET current_transform_version=?, config_override_json=?, remains_faulty=?
            WHERE id=?
            """,
            (version_id, json.dumps(override), remains, patch["pipeline_id"]),
        )


def _apply_observable_events(echo: sqlite3.Connection, patch: dict, run_id: str) -> None:
    setup = patch.get("scenario_setup") or {}
    conflicted: set[str] = set()
    for event in patch.get("observable_events") or []:
        etype = event.get("event_type")
        if etype == "destination_update_audit":
            ids = event.get("record_ids") or []
            conflicted.update(ids)
            for record_id in ids:
                echo.execute(
                    """
                    INSERT INTO dest_audit(record_id, ts, actor, change_type, payload_json)
                    VALUES (?,?,?,?,?)
                    """,
                    (
                        record_id,
                        event.get("timestamp"),
                        event.get("actor"),
                        event.get("change_type"),
                        json.dumps(event),
                    ),
                )
        elif etype == "source_snapshot_unavailable":
            for record_id in event.get("record_ids") or []:
                echo.execute(
                    "INSERT OR REPLACE INTO source_trust(record_id, trust_state, reason) VALUES (?,?,?)",
                    (record_id, "unavailable", "source_snapshot_unavailable"),
                )
        elif etype == "retry_probe":
            echo.execute(
                """
                INSERT INTO sync_logs(id, run_id, ts, level, message, context_json)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    f"LOG-RETRY-{run_id}",
                    event.get("run_id") or run_id,
                    event.get("timestamp"),
                    "WARN",
                    f"Retry probe: {event.get('result')}",
                    json.dumps(event),
                ),
            )
    if setup.get("source_trust_state") == "unavailable_for_conflicted_records":
        for record_id in conflicted:
            echo.execute(
                "INSERT OR REPLACE INTO source_trust(record_id, trust_state, reason) VALUES (?,?,?)",
                (record_id, "unavailable", "unavailable_for_conflicted_records"),
            )


def load_case(case_id: str) -> dict:
    """Create a fresh runtime and execute a real, reproducible scenario setup.

    The setup imports the read-only baseline, runs the actual synchronizer,
    applies only the scenario's controlled post-sync mutation when applicable,
    and then runs the real integrity monitor. It never loads a pre-recorded
    incident outcome as the result of a new execution.
    """
    if case_id not in active_scenario_ids():
        raise ValueError(f"Unknown active scenario: {case_id}")
    reset_runtime_files()
    finance = finance_conn()
    analytics = analytics_conn()
    echo = echo_conn()
    try:
        stats = import_baseline(finance, analytics)
        load_transform_versions(echo)
        load_history(echo)
        patch = _load_patch(case_id)
        _apply_pipeline_mutations(echo, patch)
        run_id = patch.get("execution_run_id") or f"RUN-{case_id}"
        run_sync(finance, analytics, echo, pipeline_id=PIPELINE_ID, run_id=run_id)
        _apply_destination_mutations(analytics, echo, patch)
        _apply_observable_events(echo, patch, run_id)
        findings = assess_integrity(finance, analytics, echo, run_id=run_id)
        if findings["integrity_status"] == "healthy":
            echo.commit()
            return {"case_id": case_id, "incident_id": None, "run_id": run_id, "pipeline_id": PIPELINE_ID, "findings": findings, **stats}
        incident_id = f"INC-{case_id}"
        create_incident_from_monitor(
            echo,
            run_id=run_id,
            pipeline_id=PIPELINE_ID,
            findings=findings,
            incident_id=incident_id,
            case_id=case_id,
        )
        analytics.commit()
        echo.commit()
        return {
            "case_id": case_id,
            "incident_id": incident_id,
            "run_id": run_id,
            "pipeline_id": PIPELINE_ID,
            "findings": findings,
            **stats,
        }
    finally:
        finance.close()
        analytics.close()
        echo.close()
