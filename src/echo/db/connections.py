from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from echo.config import analytics_db_path, echo_db_path, finance_db_path

SCHEMA_DIR = Path(__file__).resolve().parent


def execution_archive_path() -> Path:
    return echo_db_path().parent / "execution_history.jsonl"


def _archive_current_execution() -> None:
    """Append runtime evidence before a deliberate scenario reset."""
    path = echo_db_path()
    if not path.is_file():
        return
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        table_names = (
            "sync_runs", "sync_batches", "sync_logs", "incidents", "investigation_events",
            "hypotheses", "recovery_plans", "repair_items", "dest_snapshots",
            "verification_reports", "usage_events", "activity_events", "notifications",
        )
        evidence = {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
            for table in table_names
        }
        runs = evidence["sync_runs"]
        incidents = evidence["incidents"]
        if not runs:
            return
        record = {
            "archived_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "actual_echo_run",
            "runs": runs,
            "incidents": incidents,
            "evidence": evidence,
        }
        with execution_archive_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    finally:
        conn.close()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _apply_sql(conn: sqlite3.Connection, sql_name: str) -> None:
    sql = (SCHEMA_DIR / sql_name).read_text()
    conn.executescript(sql)
    conn.commit()


def finance_conn() -> sqlite3.Connection:
    conn = connect(finance_db_path())
    _apply_sql(conn, "schema_finance.sql")
    return conn


def analytics_conn() -> sqlite3.Connection:
    conn = connect(analytics_db_path())
    _apply_sql(conn, "schema_analytics.sql")
    return conn


def echo_conn() -> sqlite3.Connection:
    conn = connect(echo_db_path())
    _apply_sql(conn, "schema.sql")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(dest_snapshots)")}
    if "description" not in columns:
        conn.execute("ALTER TABLE dest_snapshots ADD COLUMN description TEXT")
        conn.commit()
    return conn


def reset_runtime_files() -> None:
    _archive_current_execution()
    for path in (finance_db_path(), analytics_db_path(), echo_db_path()):
        path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm", "-journal"):
            Path(str(path) + suffix).unlink(missing_ok=True)
