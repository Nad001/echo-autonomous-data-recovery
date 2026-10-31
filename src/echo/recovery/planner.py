from __future__ import annotations

import sqlite3

from echo.compare import field_mismatches, load_dest_map, load_source_map
from echo.config import REPAIR_ID_CAP
from echo.sim.transforms import effective_multiplier


def _conflicted(echo: sqlite3.Connection, record_id: str, dest_version: int | None) -> tuple[bool, str]:
    trust = echo.execute("SELECT trust_state, reason FROM source_trust WHERE record_id=?", (record_id,)).fetchone()
    if trust and trust["trust_state"] == "unavailable":
        return True, "source snapshot unavailable"
    audit = echo.execute("SELECT change_type FROM dest_audit WHERE record_id=? LIMIT 1", (record_id,)).fetchone()
    if audit:
        return True, f"destination audit: {audit['change_type']}"
    if dest_version is not None and int(dest_version) > 1:
        return True, "destination version advanced after last trusted sync"
    return False, ""


def build_plan(
    finance: sqlite3.Connection,
    analytics: sqlite3.Connection,
    echo: sqlite3.Connection,
    *,
    incident_id: str,
    pipeline_id: str,
    requested_ids: list[str] | None = None,
) -> dict:
    all_mismatches = field_mismatches(finance, analytics)
    mismatches = all_mismatches
    source = load_source_map(finance)
    dest = load_dest_map(analytics)
    if requested_ids:
        wanted = set(requested_ids[:REPAIR_ID_CAP])
        mismatches = [row for row in mismatches if row["record_id"] in wanted]
    items: list[dict] = []
    for row in mismatches[:REPAIR_ID_CAP]:
        record_id = row["record_id"]
        src = source[record_id]
        dst = dest.get(record_id)
        unsafe, reason = _conflicted(echo, record_id, row.get("dest_version"))
        field = row.get("field") or "amount_halalas"
        proposed = src["description"] if field == "description" else int(src["amount_halalas"])
        current = None if dst is None else (dst["description"] if field == "description" else int(dst["amount_halalas"]))
        items.append(
            {
                "record_id": record_id,
                "field": field,
                "current_value": current,
                "proposed_value": proposed,
                "trusted_evidence": f"source.transactions.{field}",
                "expected_source_version": int(src["source_version"]),
                "dest_version": None if dst is None else int(dst["dest_version"]),
                "safety_status": "unsafe" if unsafe else "safe",
                "reason": reason or f"restore destination {field} from trusted source",
            }
        )
    _multiplier, version_id, remains_faulty = effective_multiplier(echo, pipeline_id)
    unsafe_items = [item for item in items if item["safety_status"] != "safe"]
    safe_items = [item for item in items if item["safety_status"] == "safe"]
    if unsafe_items:
        decision = "escalate"
    elif remains_faulty and safe_items:
        decision = "quarantine_and_restore"
    elif safe_items:
        decision = "restore"
    else:
        decision = "escalate"
    return {
        "incident_id": incident_id,
        "pipeline_id": pipeline_id,
        "transform_version_id": version_id,
        "pipeline_faulty": bool(remains_faulty),
        "decision": decision,
        "items": items,
        "safe_count": len(safe_items),
        "unsafe_count": len(unsafe_items),
        # Keep the observed total independent of the investigator's bounded
        # requested-id sample so a partial plan can never auto-execute.
        "mismatch_count": len(all_mismatches),
    }
