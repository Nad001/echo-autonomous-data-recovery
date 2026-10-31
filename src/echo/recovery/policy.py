from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from echo.config import MIN_INVESTIGATION_CONFIDENCE
from echo.recovery.planner import build_plan


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def evaluate_plan(
    finance: sqlite3.Connection,
    analytics: sqlite3.Connection,
    echo: sqlite3.Connection,
    *,
    incident_id: str,
    pipeline_id: str,
    requested_ids: list[str] | None = None,
    investigation_confidence: float | None = None,
    investigation_complete: bool = True,
) -> dict:
    plan = build_plan(
        finance,
        analytics,
        echo,
        incident_id=incident_id,
        pipeline_id=pipeline_id,
        requested_ids=requested_ids,
    )
    executable = [item for item in plan["items"] if item["safety_status"] == "safe"]
    rejected = [item for item in plan["items"] if item["safety_status"] != "safe"]
    confidence_sufficient = (
        investigation_complete
        and investigation_confidence is not None
        and float(investigation_confidence) >= MIN_INVESTIGATION_CONFIDENCE
    )
    # Auto-execute only when every mismatch is eligible and the investigator
    # returned a complete, sufficiently confident interpretation.
    auto_execute = (
        plan["decision"] in {"restore", "quarantine_and_restore"}
        and not rejected
        and plan["mismatch_count"] == len(plan["items"])
        and confidence_sufficient
    )
    if plan["mismatch_count"] != len(plan["items"] ) or not confidence_sufficient:
        plan["decision"] = "escalate"
    safety = {
        "auto_execute": auto_execute,
        "rejected_count": len(rejected),
        "executable_count": len(executable),
        "pipeline_faulty": plan["pipeline_faulty"],
        "investigation_complete": investigation_complete,
        "investigation_confidence": investigation_confidence,
        "confidence_threshold": MIN_INVESTIGATION_CONFIDENCE,
        "confidence_sufficient": confidence_sufficient,
        "stale": False,
    }
    cur = echo.execute(
        "INSERT INTO recovery_plans(incident_id, status, proposal_json, safety_json, created_at) VALUES (?,?,?,?,?)",
        (
            incident_id,
            "approved" if auto_execute else "escalated",
            json.dumps(plan),
            json.dumps(safety),
            _utcnow(),
        ),
    )
    plan_id = int(cur.lastrowid)
    for item in plan["items"]:
        echo.execute(
            """
            INSERT INTO repair_items(
              plan_id, record_id, field, current_value, proposed_value, evidence,
              source_version, dest_version, safety_status, reason
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                plan_id,
                item["record_id"],
                item["field"],
                None if item["current_value"] is None else str(item["current_value"]),
                str(item["proposed_value"]),
                item["trusted_evidence"],
                item["expected_source_version"],
                item["dest_version"],
                item["safety_status"],
                item["reason"],
            ),
        )
    echo.commit()
    plan["plan_id"] = plan_id
    plan["safety"] = safety
    plan["executable_items"] = executable
    return plan
