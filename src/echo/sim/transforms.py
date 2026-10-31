from __future__ import annotations

import json
import sqlite3


def effective_multiplier(echo: sqlite3.Connection, pipeline_id: str) -> tuple[int, str, bool]:
    pipeline = echo.execute(
        "SELECT current_transform_version, config_override_json, remains_faulty FROM pipelines WHERE id=?",
        (pipeline_id,),
    ).fetchone()
    if pipeline is None:
        return 1, "unknown", False
    override = json.loads(pipeline["config_override_json"] or "{}")
    if "amount_multiplier" in override:
        return int(override["amount_multiplier"]), pipeline["current_transform_version"], bool(pipeline["remains_faulty"])
    version = echo.execute(
        "SELECT spec_json, is_trusted FROM transform_versions WHERE id=?",
        (pipeline["current_transform_version"],),
    ).fetchone()
    spec = json.loads(version["spec_json"]) if version else {}
    multiplier = int((spec.get("configuration") or {}).get("amount_multiplier") or 1)
    return multiplier, pipeline["current_transform_version"], bool(pipeline["remains_faulty"])


def apply_amount(source_amount: int, multiplier: int) -> int:
    return int(source_amount) * int(multiplier)


def trusted_multiplier() -> int:
    return 1
