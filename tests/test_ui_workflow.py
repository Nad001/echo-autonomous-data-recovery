from __future__ import annotations

import pytest


def test_successful_execution_opens_the_persisted_incident():
    from echo.ui.workflow import validate_execution_target

    setup = {"run_id": "RUN-02", "incident_id": "INC-02"}
    result = {"incident_id": "INC-02", "outcome": {"status": "verified"}}
    assert validate_execution_target(setup, result, {"id": "RUN-02"}, {"id": "INC-02"}) == "INC-02"


def test_execution_failure_without_persisted_run_stays_out_of_results():
    from echo.ui.workflow import validate_execution_target

    with pytest.raises(RuntimeError, match="persisted synchronization run"):
        validate_execution_target({"run_id": "RUN-02", "incident_id": "INC-02"}, {"error": "backend failed"}, None, None)


def test_duplicate_click_is_blocked_while_execution_is_in_progress():
    from echo.ui.workflow import can_start_execution

    assert can_start_execution(confirmed=True, in_progress=False) is True
    assert can_start_execution(confirmed=True, in_progress=True) is False
    assert can_start_execution(confirmed=False, in_progress=False) is False
