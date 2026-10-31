from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from echo.notify.service import emit_activity, emit_notification


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def verify_incident(
    finance: sqlite3.Connection,
    analytics: sqlite3.Connection,
    echo: sqlite3.Connection,
    *,
    incident_id: str,
    pipeline_id: str,
    executed_ids: set[str],
) -> dict:
    snapshots = {
        row["record_id"]: row
        for row in echo.execute(
            "SELECT record_id, amount_halalas, description, dest_version FROM dest_snapshots WHERE incident_id=?",
            (incident_id,),
        )
    }
    dest_rows = analytics.execute("SELECT record_id, amount_halalas, description, dest_version FROM fact_transactions").fetchall()
    source = {
        row["record_id"]: dict(row)
        for row in finance.execute("SELECT record_id, amount_halalas, description FROM transactions")
    }
    failures: list[str] = []
    healthy_changed = 0
    for dest in dest_rows:
        record_id = dest["record_id"]
        snap = snapshots.get(record_id)
        if record_id in executed_ids:
            if int(dest["amount_halalas"]) != int(source[record_id]["amount_halalas"]):
                failures.append(f"repaired {record_id} amount does not match source")
            if (dest["description"] or "") != (source[record_id]["description"] or ""):
                failures.append(f"repaired {record_id} description does not match source")
            continue
        if snap is None:
            continue
        if int(dest["amount_halalas"]) != int(snap["amount_halalas"]) or (dest["description"] or "") != (snap["description"] or ""):
            healthy_changed += 1
            failures.append(f"untargeted {record_id} changed")
        if int(dest["dest_version"]) != int(snap["dest_version"]):
            failures.append(f"dest_version changed for {record_id}")
    passed = not failures
    details = {
        "passed": passed,
        "failures": failures[:50],
        "failure_count": len(failures),
        "incorrect_healthy_modifications": healthy_changed,
        "verified_repairs": len(executed_ids),
        "independent": True,
    }
    echo.execute(
        "INSERT INTO verification_reports(incident_id, passed, details_json, created_at) VALUES (?,?,?,?)",
        (incident_id, 1 if passed else 0, json.dumps(details), _utcnow()),
    )
    recovery_status = "verified" if passed else "failed"
    echo.execute(
        "UPDATE incidents SET recovery_status=? WHERE id=?",
        (recovery_status, incident_id),
    )
    emit_activity(
        echo,
        "verification_completed",
        "Independent verification passed" if passed else "Independent verification failed",
        incident_id=incident_id,
    )
    emit_notification(
        echo,
        incident_id=incident_id,
        pipeline_id=pipeline_id,
        severity="low" if passed else "high",
        status=recovery_status,
        summary="Verified recovery completed" if passed else "Recovery verification failed",
    )
    echo.commit()
    details["recovery_status"] = recovery_status
    return details
