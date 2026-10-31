"""Small, side-effect-free helpers for the Streamlit execution handoff."""

from __future__ import annotations

from typing import Any


def can_start_execution(*, confirmed: bool, in_progress: bool) -> bool:
    """Allow one explicit execution only when it is confirmed and idle."""
    return bool(confirmed) and not bool(in_progress)


def validate_execution_target(
    setup: dict[str, Any],
    result: dict[str, Any] | None,
    persisted_run: dict[str, Any] | None,
    persisted_incident: dict[str, Any] | None,
) -> str | None:
    """Validate that execution returned the persisted objects the UI will open."""
    if not persisted_run:
        raise RuntimeError("ECHO did not return a persisted synchronization run.")
    expected_incident = setup.get("incident_id")
    returned_incident = result.get("incident_id") if isinstance(result, dict) else None
    if expected_incident and not persisted_incident:
        raise RuntimeError("ECHO did not return the persisted incident created by this run.")
    if expected_incident and returned_incident and expected_incident != returned_incident:
        raise RuntimeError("ECHO returned an incident different from the persisted scenario result.")
    return returned_incident or expected_incident
