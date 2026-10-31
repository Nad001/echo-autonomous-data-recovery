from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from echo.notify.service import emit_activity


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def snapshot_destination(analytics: sqlite3.Connection, echo: sqlite3.Connection, incident_id: str) -> int:
    rows = analytics.execute("SELECT record_id, amount_halalas, description, dest_version FROM fact_transactions").fetchall()
    echo.execute("DELETE FROM dest_snapshots WHERE incident_id=?", (incident_id,))
    echo.executemany(
        "INSERT INTO dest_snapshots(incident_id, record_id, amount_halalas, description, dest_version, taken_at) VALUES (?,?,?,?,?,?)",
        [(incident_id, r["record_id"], r["amount_halalas"], r["description"], r["dest_version"], _utcnow()) for r in rows],
    )
    echo.commit()
    return len(rows)


def apply_repairs(
    analytics: sqlite3.Connection,
    echo: sqlite3.Connection,
    *,
    incident_id: str,
    items: list[dict],
) -> dict:
    snapshot_destination(analytics, echo, incident_id)
    applied = 0
    try:
        for item in items:
            if item["safety_status"] != "safe":
                continue
            field = item["field"]
            if field not in {"amount_halalas", "description"}:
                raise RuntimeError(f"Unsupported repair field: {field}")
            cursor = analytics.execute(
                f"UPDATE fact_transactions SET {field}=?, updated_at=? WHERE record_id=? AND {field}=?",
                (item["proposed_value"], _utcnow(), item["record_id"], item["current_value"]),
            )
            if cursor.rowcount == 0:
                current = analytics.execute(f"SELECT {field} FROM fact_transactions WHERE record_id=?", (item["record_id"],)).fetchone()
                if current and current[field] == item["proposed_value"]:
                    continue
                raise RuntimeError(f"Stale repair plan for {item['record_id']}")
            applied += 1
        analytics.commit()
    except Exception:
        analytics.rollback()
        raise
    echo.execute("UPDATE recovery_plans SET status='executed' WHERE incident_id=?", (incident_id,))
    emit_activity(echo, "recovery_applied", f"Applied {applied} record repairs", incident_id=incident_id)
    echo.commit()
    return {"applied": applied}
