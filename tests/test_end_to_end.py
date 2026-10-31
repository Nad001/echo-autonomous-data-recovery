from __future__ import annotations

import hashlib

import pytest


@pytest.fixture()
def runtime(tmp_path, monkeypatch):
    import echo.config as config

    monkeypatch.setattr(config, "RUNTIME_DIR", tmp_path)
    return tmp_path


def _run(case_id: str):
    from echo.ingest.scenarios import load_case
    from echo.worker.main import process_one

    setup = load_case(case_id)
    result = process_one()
    return setup, result


def test_healthy_synchronization_has_no_incident_or_changes(runtime):
    setup, result = _run("SCENARIO-01")
    assert setup["transactions"] == 5000
    assert setup["incident_id"] is None
    assert setup["findings"]["discrepancy_count"] == 0
    assert result is None


def test_single_numerical_corruption_is_repaired_and_verified(runtime):
    from echo.db.connections import echo_conn

    setup, result = _run("SCENARIO-02")
    assert setup["findings"]["discrepancy_count"] == 1
    assert result is not None
    assert result["outcome"]["status"] == "verified"
    assert result["outcome"]["verification"]["verified_repairs"] == 1
    assert result["outcome"]["verification"]["incorrect_healthy_modifications"] == 0
    echo = echo_conn()
    try:
        pipeline = echo.execute("SELECT status FROM pipelines WHERE id=?", (setup["pipeline_id"],)).fetchone()
        assert pipeline["status"] == "active"
        assert echo.execute("SELECT 1 FROM activity_events WHERE incident_id=? AND kind='pipeline_quarantined'", (setup["incident_id"],)).fetchone() is None
    finally:
        echo.close()


def test_model_uncertainty_about_mechanism_does_not_veto_safe_repair(runtime, monkeypatch):
    """A safe deterministic plan may proceed even if the model asks for review of the cause."""
    from echo.agent.openai_client import HeuristicLLM
    from echo.worker import main as worker

    def investigate_with_cause_uncertainty(ctx):
        turn = HeuristicLLM(ctx)._final_turn("call-final", "mock-final")
        intent = dict(turn.arguments)
        intent["escalate"] = True
        intent["strategy"] = "escalate"
        intent["human_review_reason"] = "The exact record-level mechanism is not confirmed."
        intent["budget"] = {
            "tool_calls": 0,
            "final_response_calls": 1,
            "total_tool_calls": 1,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_usd": 0.0,
            "max_estimated_usd": 0.1,
            "elapsed_seconds": 0.0,
            "model": "heuristic-mock",
        }
        intent["investigation_state"] = "complete"
        intent["model_submitted"] = True
        return intent

    monkeypatch.setattr(worker, "investigate", investigate_with_cause_uncertainty)
    setup, result = _run("SCENARIO-02")
    assert result["outcome"]["status"] == "verified"
    assert result["outcome"]["plan"]["safety"]["auto_execute"] is True
    assert result["outcome"]["verification"]["verified_repairs"] == 1


def test_partial_text_corruption_is_repaired_without_healthy_changes(runtime):
    setup, result = _run("SCENARIO-03")
    assert setup["findings"]["discrepancy_count"] == 3
    assert result is not None
    assert result["outcome"]["status"] == "verified"
    assert result["outcome"]["verification"]["verified_repairs"] == 3
    assert result["outcome"]["verification"]["incorrect_healthy_modifications"] == 0


def test_complete_corruption_is_detected_and_not_partially_repaired(runtime):
    from echo.db.connections import echo_conn

    setup, result = _run("SCENARIO-04")
    assert setup["findings"]["discrepancy_count"] == 5000
    assert result is not None
    assert result["outcome"]["status"] == "escalated"
    assert result["outcome"]["plan"]["pipeline_faulty"] is True
    assert result["outcome"]["plan"]["safety"]["auto_execute"] is False
    echo = echo_conn()
    try:
        pipeline = echo.execute("SELECT status FROM pipelines WHERE id=?", (setup["pipeline_id"],)).fetchone()
        assert pipeline["status"] == "quarantined"
    finally:
        echo.close()


def test_conflicting_update_escalates_and_preserves_destination(runtime):
    from echo.db.connections import analytics_conn

    setup, result = _run("SCENARIO-05")
    assert setup["findings"]["discrepancy_count"] == 1
    assert result is not None
    assert result["outcome"]["status"] == "escalated"
    assert result["outcome"]["plan"]["unsafe_count"] == 1
    analytics = analytics_conn()
    try:
        row = analytics.execute("SELECT amount_halalas FROM fact_transactions WHERE record_id='TX-000005'").fetchone()
        assert row["amount_halalas"] != 0
    finally:
        analytics.close()


def test_package_transaction_file_is_unchanged(runtime):
    from echo.config import PACKAGE_DIR

    path = PACKAGE_DIR / "baseline" / "transactions.csv"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    _run("SCENARIO-02")
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert after == before


def test_active_registry_has_exactly_five_cases_and_reset_archives_prior_evidence(runtime):
    import json
    from pathlib import Path
    from echo.config import PACKAGE_DIR

    registry = json.loads((PACKAGE_DIR / "scenario_registry.json").read_text())
    assert [item["case_id"] for item in registry["active_scenarios"]] == [
        "SCENARIO-01", "SCENARIO-02", "SCENARIO-03", "SCENARIO-04", "SCENARIO-05"
    ]
    _run("SCENARIO-02")
    _run("SCENARIO-03")
    archive = Path(runtime) / "execution_history.jsonl"
    records = [json.loads(line) for line in archive.read_text().splitlines() if line.strip()]
    assert records
    assert records[-1]["source"] == "actual_echo_run"
    assert records[-1]["evidence"]["incidents"]


def test_independent_verifier_catches_a_bad_repair(runtime):
    from echo.db.connections import analytics_conn, echo_conn, finance_conn
    from echo.recovery.verifier import verify_incident

    setup, result = _run("SCENARIO-02")
    assert result["outcome"]["status"] == "verified"
    finance, analytics, echo = finance_conn(), analytics_conn(), echo_conn()
    try:
        source = finance.execute("SELECT amount_halalas FROM transactions WHERE record_id='TX-000001'").fetchone()["amount_halalas"]
        analytics.execute("UPDATE fact_transactions SET amount_halalas=? WHERE record_id='TX-000001'", (source + 1,))
        analytics.commit()
        verification = verify_incident(finance, analytics, echo, incident_id=setup["incident_id"], pipeline_id=setup["pipeline_id"], executed_ids={"TX-000001"})
        assert verification["passed"] is False
        assert verification["failure_count"] > 0
    finally:
        finance.close()
        analytics.close()
        echo.close()


def test_low_confidence_or_incomplete_investigation_cannot_auto_execute(runtime):
    from echo.db.connections import analytics_conn, echo_conn, finance_conn
    from echo.recovery.policy import evaluate_plan

    setup, result = _run("SCENARIO-03")
    finance, analytics, echo = finance_conn(), analytics_conn(), echo_conn()
    try:
        plan = evaluate_plan(
            finance,
            analytics,
            echo,
            incident_id=setup["incident_id"],
            pipeline_id=setup["pipeline_id"],
            investigation_confidence=0.1,
            investigation_complete=False,
        )
        assert plan["decision"] == "escalate"
        assert plan["safety"]["auto_execute"] is False
        assert plan["safety"]["confidence_sufficient"] is False
    finally:
        finance.close()
        analytics.close()
        echo.close()


def test_recovery_display_separates_proposed_from_applied_values(runtime):
    setup, result = _run("SCENARIO-05")
    assert result["outcome"]["status"] == "escalated"
    from echo.ui.app import comparison_rows, incident_data

    rows = comparison_rows(incident_data(setup["incident_id"]))
    assert rows
    row = rows[0]
    assert row["Proposed replacement"] != "—"
    assert row["Applied replacement"] == "—"
    assert row["Verified result"] == "Not independently verified"


def test_investigation_view_uses_authoritative_safety_plan_for_safe_repair(runtime):
    """A safe, verified repair must not be mislabeled as human-review-only."""
    from echo.ui.app import incident_data, investigation_summary

    setup, result = _run("SCENARIO-02")
    assert result["outcome"]["status"] == "verified"
    data = incident_data(setup["incident_id"])
    summary = investigation_summary(data)

    assert data["plan_json"]["decision"] == "restore"
    assert data["safety"]["auto_execute"] is True
    assert summary["strategy"] == "restore"
