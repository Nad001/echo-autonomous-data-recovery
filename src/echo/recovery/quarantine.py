from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from echo.notify.service import emit_activity, emit_notification


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def quarantine_pipeline(echo: sqlite3.Connection, pipeline_id: str, incident_id: str, reason: str) -> None:
    echo.execute(
        """
        UPDATE pipelines
        SET status='quarantined', quarantined_at=?, resume_blocked_reason=?
        WHERE id=?
        """,
        (_utcnow(), reason, pipeline_id),
    )
    emit_activity(echo, "pipeline_quarantined", reason, incident_id=incident_id)
    emit_notification(
        echo,
        incident_id=incident_id,
        pipeline_id=pipeline_id,
        severity="high",
        status="quarantined",
        summary=f"Pipeline quarantined: {reason}",
    )
    echo.commit()


def pipeline_is_quarantined(echo: sqlite3.Connection, pipeline_id: str) -> bool:
    row = echo.execute("SELECT status FROM pipelines WHERE id=?", (pipeline_id,)).fetchone()
    return bool(row and row["status"] == "quarantined")
