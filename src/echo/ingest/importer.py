from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from echo.ingest.contract import package_path, validate_package


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_csv(conn: sqlite3.Connection, table: str, path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if not rows:
        return 0
    columns = list(rows[0].keys())
    placeholders = ",".join("?" for _ in columns)
    col_sql = ",".join(columns)
    values = [tuple(row[c] for c in columns) for row in rows]
    conn.execute(f"DELETE FROM {table}")
    conn.executemany(f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})", values)
    return len(values)


def load_transform_versions(echo: sqlite3.Connection) -> None:
    payload = json.loads(package_path("pipeline", "transform_versions.json").read_text())
    echo.execute("DELETE FROM transform_versions")
    echo.execute("DELETE FROM pipelines")
    echo.execute(
        "INSERT INTO pipelines(id, name, status, current_transform_version, remains_faulty) VALUES (?,?,?,?,0)",
        (payload["pipeline_id"], "Finance to Analytics", "active", payload["versions"][0]["id"]),
    )
    for version in payload["versions"]:
        echo.execute(
            """
            INSERT INTO transform_versions(id, pipeline_id, name, spec_json, is_trusted)
            VALUES (?,?,?,?,?)
            """,
            (
                version["id"],
                payload["pipeline_id"],
                version.get("name"),
                json.dumps(version),
                1 if version.get("trusted") else 0,
            ),
        )


def load_history(echo: sqlite3.Connection) -> None:
    # The package uses descriptive source headers; control-plane tables use
    # stable internal names. Keep this adapter explicit so the package remains
    # source-of-truth and can evolve without unsafe SQL interpolation.
    for table in ("sync_runs", "sync_batches", "sync_logs"):
        echo.execute(f"DELETE FROM {table}")
    with package_path("history", "sync_runs.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            echo.execute(
                "INSERT INTO sync_runs(id,pipeline_id,started_at,finished_at,records_processed,execution_status,integrity_status,transform_version_id) VALUES (?,?,?,?,?,?,?,?)",
                (row["run_id"], row["pipeline_id"], row["started_at"], row["finished_at"], int(row["records_processed"]), row["execution_status"], row["integrity_status"], row["transformation_version_id"]),
            )
    with package_path("history", "sync_batches.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            echo.execute(
                "INSERT INTO sync_batches(id,run_id,batch_seq,started_at,record_count,integrity_status,transform_version_id) VALUES (?,?,?,?,?,?,?)",
                (row["batch_id"], row["run_id"], int(row["batch_seq"]), row["started_at"], int(row["record_count"]), row["integrity_status"], row["transformation_version_id"]),
            )
    with package_path("history", "sync_logs.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            echo.execute(
                "INSERT INTO sync_logs(id,run_id,ts,level,message,context_json) VALUES (?,?,?,?,?,?)",
                (row["log_id"], row["run_id"], row["timestamp"], row["level"], row["message"], row["context_json"]),
            )
    echo.commit()


def import_baseline(finance: sqlite3.Connection, analytics: sqlite3.Connection) -> dict:
    missing = validate_package()
    if missing:
        raise FileNotFoundError(f"Dataset package incomplete: {missing}")
    tx_path = package_path("baseline", "transactions.csv")
    original_hash = file_sha256(tx_path)
    n_accounts = import_csv(finance, "accounts", package_path("baseline", "accounts.csv"))
    n_tx = import_csv(finance, "transactions", tx_path)
    finance.commit()
    rows = finance.execute("SELECT * FROM transactions").fetchall()
    analytics.execute("DELETE FROM fact_transactions")
    analytics.executemany(
        """
        INSERT INTO fact_transactions(
          record_id, account_id, occurred_at, amount_halalas, currency, description,
          source_version, dest_version, last_sync_run_id, last_transform_version, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                r["record_id"],
                r["account_id"],
                r["occurred_at"],
                r["amount_halalas"],
                r["currency"],
                r["description"],
                r["source_version"],
                1,
                "RUN-0020",
                "transform-v1",
                r["updated_at"],
            )
            for r in rows
        ],
    )
    analytics.commit()
    after_hash = file_sha256(tx_path)
    if after_hash != original_hash:
        raise RuntimeError("Baseline dataset file changed during import")
    return {
        "accounts": n_accounts,
        "transactions": n_tx,
        "baseline_sha256": original_hash,
    }
