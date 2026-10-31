from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def claim_job(echo: sqlite3.Connection, *, lease_seconds: int = 120) -> sqlite3.Row | None:
    now = _utcnow()
    lease = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    echo.execute("BEGIN IMMEDIATE")
    try:
        job = echo.execute(
            """SELECT * FROM jobs WHERE status='queued' OR (status='running' AND lease_until < ?)
               ORDER BY id LIMIT 1""", (now,)
        ).fetchone()
        if job is None:
            echo.commit()
            return None
        echo.execute(
            """UPDATE jobs SET status='running', lease_until=?, attempts=attempts+1, updated_at=? WHERE id=?""",
            (lease, now, job["id"]),
        )
        echo.commit()
        return echo.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
    except Exception:
        echo.rollback()
        raise


def finish_job(echo: sqlite3.Connection, job_id: int, *, error: str | None = None) -> None:
    now = _utcnow()
    if error:
        echo.execute("UPDATE jobs SET status='failed', error=?, lease_until=NULL, updated_at=? WHERE id=?", (error[:2000], now, job_id))
    else:
        echo.execute("UPDATE jobs SET status='completed', lease_until=NULL, updated_at=? WHERE id=?", (now, job_id))
    echo.commit()
