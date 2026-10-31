from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from echo.sim.transforms import apply_amount, effective_multiplier


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_sync(
    finance: sqlite3.Connection,
    analytics: sqlite3.Connection,
    echo: sqlite3.Connection,
    *,
    pipeline_id: str,
    run_id: str,
) -> dict:
    pipeline = echo.execute("SELECT status FROM pipelines WHERE id=?", (pipeline_id,)).fetchone()
    if pipeline and pipeline["status"] == "quarantined":
        raise RuntimeError("Pipeline is quarantined; synchronization refused")
    multiplier, version_id, _faulty = effective_multiplier(echo, pipeline_id)
    started = _utcnow()
    echo.execute(
        """
        INSERT OR REPLACE INTO sync_runs(
          id, pipeline_id, started_at, finished_at, records_processed,
          execution_status, integrity_status, transform_version_id
        ) VALUES (?,?,?,?,?, 'running', 'pending', ?)
        """,
        (run_id, pipeline_id, started, None, 0, version_id),
    )
    source_rows = finance.execute("SELECT * FROM transactions").fetchall()
    written = 0
    for row in source_rows:
        amount = apply_amount(int(row["amount_halalas"]), multiplier)
        existing = analytics.execute(
            "SELECT dest_version FROM fact_transactions WHERE record_id=?",
            (row["record_id"],),
        ).fetchone()
        dest_version = int(existing["dest_version"]) if existing else 1
        analytics.execute(
            """
            INSERT INTO fact_transactions(
              record_id, account_id, occurred_at, amount_halalas, currency, description,
              source_version, dest_version, last_sync_run_id, last_transform_version, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(record_id) DO UPDATE SET
              amount_halalas=excluded.amount_halalas,
              last_sync_run_id=excluded.last_sync_run_id,
              last_transform_version=excluded.last_transform_version,
              updated_at=excluded.updated_at
            """,
            (
                row["record_id"],
                row["account_id"],
                row["occurred_at"],
                amount,
                row["currency"],
                row["description"],
                row["source_version"],
                dest_version,
                run_id,
                version_id,
                _utcnow(),
            ),
        )
        written += 1
    batch_size = 500
    for offset in range(0, written, batch_size):
        echo.execute(
            """INSERT OR REPLACE INTO sync_batches(
               id, run_id, batch_seq, started_at, record_count, integrity_status, transform_version_id
               ) VALUES (?,?,?,?,?,?,?)""",
            (f"{run_id}-B{offset // batch_size + 1:02d}", run_id, offset // batch_size + 1, started, min(batch_size, written - offset), "pending", version_id),
        )
    finished = _utcnow()
    echo.execute(
        """
        UPDATE sync_runs
        SET finished_at=?, records_processed=?, execution_status='succeeded', integrity_status='unknown'
        WHERE id=?
        """,
        (finished, written, run_id),
    )
    echo.execute(
        """
        INSERT INTO sync_logs(id, run_id, ts, level, message, context_json)
        VALUES (?,?,?,?,?,?)
        """,
        (
            f"LOG-{run_id}-DONE",
            run_id,
            finished,
            "INFO",
            f"Synchronization completed: {written} records written; execution succeeded",
            json.dumps({"rows_written": written, "execution_errors": 0, "transform": version_id}),
        ),
    )
    finance.commit()
    analytics.commit()
    echo.commit()
    return {"run_id": run_id, "records_processed": written, "execution_status": "succeeded", "transform_version_id": version_id}
