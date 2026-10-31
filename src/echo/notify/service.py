from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def emit_notification(
    echo: sqlite3.Connection,
    *,
    incident_id: str | None,
    pipeline_id: str | None,
    severity: str,
    status: str,
    summary: str,
) -> None:
    echo.execute(
        """
        INSERT INTO notifications(incident_id, pipeline_id, ts, severity, unread, status, summary, link)
        VALUES (?,?,?,?,1,?,?,?)
        """,
        (
            incident_id,
            pipeline_id,
            _utcnow(),
            severity,
            status,
            summary,
            f"#incident/{incident_id}" if incident_id else "#overview",
        ),
    )


def emit_activity(
    echo: sqlite3.Connection,
    kind: str,
    summary: str,
    *,
    incident_id: str | None = None,
    run_id: str | None = None,
) -> None:
    echo.execute(
        "INSERT INTO activity_events(ts, kind, summary, incident_id, run_id) VALUES (?,?,?,?,?)",
        (_utcnow(), kind, summary, incident_id, run_id),
    )


def mark_read(echo: sqlite3.Connection, notification_id: int) -> None:
    echo.execute("UPDATE notifications SET unread=0 WHERE id=?", (notification_id,))
