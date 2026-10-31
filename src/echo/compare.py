from __future__ import annotations

import sqlite3


def load_source_map(finance: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {row["record_id"]: row for row in finance.execute("SELECT * FROM transactions")}


def load_dest_map(analytics: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {row["record_id"]: row for row in analytics.execute("SELECT * FROM fact_transactions")}


def amount_mismatches(
    finance: sqlite3.Connection,
    analytics: sqlite3.Connection,
) -> list[dict]:
    source = load_source_map(finance)
    dest = load_dest_map(analytics)
    out: list[dict] = []
    for record_id, src in source.items():
        dst = dest.get(record_id)
        if dst is None:
            out.append(
                {
                    "record_id": record_id,
                    "kind": "missing_destination",
                    "source_amount": int(src["amount_halalas"]),
                    "dest_amount": None,
                    "source_version": int(src["source_version"]),
                    "dest_version": None,
                }
            )
            continue
        if int(src["amount_halalas"]) != int(dst["amount_halalas"]):
            out.append(
                {
                    "record_id": record_id,
                    "kind": "amount",
                    "source_amount": int(src["amount_halalas"]),
                    "dest_amount": int(dst["amount_halalas"]),
                    "source_version": int(src["source_version"]),
                    "dest_version": int(dst["dest_version"]),
                    "ratio": (int(dst["amount_halalas"]) / int(src["amount_halalas"]))
                    if int(src["amount_halalas"])
                    else None,
                }
            )
    return out


def field_mismatches(
    finance: sqlite3.Connection,
    analytics: sqlite3.Connection,
) -> list[dict]:
    """Compare the supported trusted fields without mutating either database."""
    source = load_source_map(finance)
    dest = load_dest_map(analytics)
    out: list[dict] = []
    for record_id, src in source.items():
        dst = dest.get(record_id)
        if dst is None:
            out.append({
                "record_id": record_id,
                "field": "record",
                "kind": "missing_destination",
                "source_value": record_id,
                "dest_value": None,
                "source_version": int(src["source_version"]),
                "dest_version": None,
            })
            continue
        if int(src["amount_halalas"]) != int(dst["amount_halalas"]):
            source_amount = int(src["amount_halalas"])
            dest_amount = int(dst["amount_halalas"])
            out.append({
                "record_id": record_id,
                "field": "amount_halalas",
                "kind": "amount",
                "source_value": source_amount,
                "dest_value": dest_amount,
                "source_amount": source_amount,
                "dest_amount": dest_amount,
                "source_version": int(src["source_version"]),
                "dest_version": int(dst["dest_version"]),
                "ratio": (dest_amount / source_amount) if source_amount else None,
            })
        if (src["description"] or "") != (dst["description"] or ""):
            out.append({
                "record_id": record_id,
                "field": "description",
                "kind": "text",
                "source_value": src["description"],
                "dest_value": dst["description"],
                "source_version": int(src["source_version"]),
                "dest_version": int(dst["dest_version"]),
            })
    return out
