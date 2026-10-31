from __future__ import annotations

import json

import pytest


@pytest.fixture()
def runtime(tmp_path, monkeypatch):
    import echo.config as config

    monkeypatch.setattr(config, "RUNTIME_DIR", tmp_path)
    return tmp_path


def test_live_mode_requires_key(monkeypatch):
    import echo.agent.openai_client as client

    monkeypatch.setattr(client, "LLM_MODE", "openai")
    monkeypatch.setattr(client, "OPENAI_API_KEY", "")
    try:
        client.build_llm(None)  # type: ignore[arg-type]
    except RuntimeError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("live mode must fail when the key is absent")


def test_default_configuration_is_offline(monkeypatch):
    import echo.agent.openai_client as client

    monkeypatch.setattr(client, "LLM_MODE", "mock")
    assert client.build_llm(None).model == "heuristic-mock"  # type: ignore[arg-type]


def test_env_file_is_ignored():
    from pathlib import Path

    assert ".env" in Path(".gitignore").read_text().splitlines()


def test_text_investigation_uses_text_diagnostics(runtime):
    from echo.agent.openai_client import HeuristicLLM
    from echo.agent.tools import ToolContext, profile_text
    from echo.compare import field_mismatches
    from echo.db.connections import analytics_conn, echo_conn, finance_conn
    from echo.ingest.scenarios import load_case

    setup = load_case("SCENARIO-03")
    finance, analytics, echo = finance_conn(), analytics_conn(), echo_conn()
    try:
        ctx = ToolContext(finance, analytics, echo, setup["incident_id"])
        profile = profile_text(ctx)
        assert profile["text_mismatch_count"] == 3
        assert profile["examples"]
        assert {example["destination_value"] for example in profile["examples"]} == {"Bank transfe", "Sppulier payment", "Refnd"}
        assert set(profile["change_type_counts"]) == {"truncation", "scrambled_characters", "partial_character_loss"}
        assert all(row["field"] == "description" for row in field_mismatches(finance, analytics) if row["field"] == "description")
        llm = HeuristicLLM(ctx)
        calls = [llm.next_turn(input_payload={}, previous_response_id=None).tool_name for _ in range(7)]
        assert "profile_text" in calls
        assert "amount_scale" not in calls
        assert calls[-1] == "submit_investigation"
    finally:
        finance.close()
        analytics.close()
        echo.close()


def test_evidence_package_is_domain_neutral_and_bounded(runtime):
    from echo.agent.tools import ToolContext, build_evidence_package
    from echo.db.connections import analytics_conn, echo_conn, finance_conn
    from echo.ingest.scenarios import load_case

    setup = load_case("SCENARIO-03")
    finance, analytics, echo = finance_conn(), analytics_conn(), echo_conn()
    try:
        evidence = build_evidence_package(ToolContext(finance, analytics, echo, setup["incident_id"]))
        assert evidence["scope"]["compared_records"] == 5000
        assert evidence["discrepancies"]["count"] == 3
        assert evidence["discrepancies"]["field_types"]["description"] == "text_or_other"
        assert len(evidence["discrepancies"]["examples"]) <= 10
        assert "schema" in evidence and "diagnostics" in evidence
    finally:
        finance.close()
        analytics.close()
        echo.close()


def test_evidence_package_captures_numeric_fields(runtime):
    from echo.agent.tools import ToolContext, build_evidence_package
    from echo.db.connections import analytics_conn, echo_conn, finance_conn
    from echo.ingest.scenarios import load_case

    setup = load_case("SCENARIO-02")
    finance, analytics, echo = finance_conn(), analytics_conn(), echo_conn()
    try:
        evidence = build_evidence_package(ToolContext(finance, analytics, echo, setup["incident_id"]))
        assert evidence["discrepancies"]["count"] == 1
        assert evidence["discrepancies"]["field_types"]["amount_halalas"] == "numeric"
        assert evidence["discrepancies"]["examples"][0]["source_value"] != evidence["discrepancies"]["examples"][0]["destination_value"]
    finally:
        finance.close()
        analytics.close()


def test_multiple_diagnostics_are_returned_before_final_interpretation(runtime, monkeypatch):
    from echo.agent import loop
    from echo.agent.openai_client import LLMTurn
    from echo.agent.tools import ToolContext
    from echo.db.connections import analytics_conn, echo_conn, finance_conn
    from echo.ingest.scenarios import load_case

    setup = load_case("SCENARIO-03")
    finance, analytics, echo = finance_conn(), analytics_conn(), echo_conn()
    try:
        final_args = {
            "title": "Observed text-field discrepancy",
            "summary": "The destination text differs from the trusted source in three records.",
            "observed_issue": "Three persisted description values differ.",
            "suspected_root_cause": "A text transformation occurred during synchronization; the exact cause is not confirmed.",
            "supporting_evidence": ["The comparison found three description mismatches.", "Text profiling found bounded changes."],
            "suspected_cause": "observed_text_transformation",
            "confidence": 0.8,
            "affected_record_ids": ["TX-000001", "TX-000002", "TX-000003"],
            "earliest_batch_id": None,
            "pipeline_safe_to_retry": True,
            "escalate": False,
            "uncertainty": ["Exact upstream cause is not confirmed."],
            "strategy": "restore",
            "safety_concerns": ["Deterministic safety policy must authorize repair."],
            "human_review_reason": None,
            "finding_summary": "Three persisted description values differ.",
            "evidence_summary": "Comparison and text profiling support the finding.",
            "recommended_action": "Restore only eligible fields from trusted source evidence.",
        }

        class MultiStep:
            model = "local-fixture"
            step = 0

            def next_turn(self, *, input_payload, previous_response_id):
                self.step += 1
                if self.step == 1:
                    calls = [
                        {"tool_name": "compare_records", "arguments": {}, "call_id": "call-compare"},
                        {"tool_name": "profile_text", "arguments": {}, "call_id": "call-text"},
                    ]
                    return LLMTurn("compare_records", {}, "call-compare", "resp-diagnostics", function_calls=calls, response_status="completed")
                return LLMTurn("submit_investigation", final_args, "call-final", "resp-final", function_calls=[{"tool_name": "submit_investigation", "arguments": final_args, "call_id": "call-final"}], response_status="completed")

        monkeypatch.setattr(loop, "build_llm", lambda ctx: MultiStep())
        result = loop.investigate(ToolContext(finance, analytics, echo, setup["incident_id"]))
        assert result["investigation_state"] == "complete"
        assert result["title"] == "Observed text-field discrepancy"
        events = [dict(row) for row in echo.execute("SELECT kind, payload_json FROM investigation_events WHERE incident_id=? ORDER BY id", (setup["incident_id"],))]
        tool_events = [event for event in events if event["kind"] == "tool_executed"]
        assert [json.loads(event["payload_json"])["tool"] for event in tool_events[:2]] == ["compare_records", "profile_text"]
    finally:
        finance.close()
        analytics.close()
        echo.close()


def test_eight_diagnostic_calls_still_get_a_reserved_final_turn(runtime, monkeypatch):
    from echo.agent import loop
    from echo.agent.openai_client import LLMTurn
    from echo.agent.tools import ToolContext
    from echo.db.connections import analytics_conn, echo_conn, finance_conn
    from echo.ingest.scenarios import load_case

    setup = load_case("SCENARIO-03")
    finance, analytics, echo = finance_conn(), analytics_conn(), echo_conn()
    try:
        final_args = {
            "title": "Observed discrepancy",
            "summary": "The destination differs from the source.",
            "observed_issue": "Persisted fields differ.",
            "suspected_root_cause": "Root cause not confirmed.",
            "supporting_evidence": ["Comparison evidence was recorded."],
            "suspected_cause": "unknown",
            "confidence": None,
            "affected_record_ids": ["TX-000001"],
            "earliest_batch_id": None,
            "pipeline_safe_to_retry": False,
            "escalate": True,
            "uncertainty": ["Evidence is insufficient."],
            "strategy": "escalate",
            "safety_concerns": ["Human review is required."],
            "human_review_reason": "The cause is not confirmed.",
            "finding_summary": "Persisted fields differ.",
            "evidence_summary": "Comparison evidence was recorded.",
            "recommended_action": "Preserve the destination and review manually.",
        }

        class EightThenFinal:
            model = "local-fixture"
            step = 0

            def next_turn(self, *, input_payload, previous_response_id):
                self.step += 1
                if self.step == 1:
                    names = ["inspect_incident", "inspect_sync_run", "compare_records", "profile_fields", "inspect_sync_logs", "profile_text", "test_hypothesis", "inspect_record_history"]
                    calls = [{"tool_name": name, "arguments": ({"run_id": "RUN-1"} if name in {"inspect_sync_run", "inspect_sync_logs"} else {"record_ids": ["TX-000001"]} if name == "inspect_record_history" else {"hypothesis": "text_truncation"} if name == "test_hypothesis" else {}), "call_id": f"call-{index}"} for index, name in enumerate(names)]
                    return LLMTurn(names[0], calls[0]["arguments"], calls[0]["call_id"], "resp-eight", function_calls=calls, response_status="completed")
                return LLMTurn("submit_investigation", final_args, "call-final", "resp-final", function_calls=[{"tool_name": "submit_investigation", "arguments": final_args, "call_id": "call-final"}], response_status="completed")

        monkeypatch.setattr(loop, "build_llm", lambda ctx: EightThenFinal())
        result = loop.investigate(ToolContext(finance, analytics, echo, setup["incident_id"]))
        assert result["investigation_state"] == "complete"
        assert result["budget"]["tool_calls"] == 8
        assert result["budget"]["final_response_calls"] == 1
    finally:
        finance.close()
        analytics.close()
        echo.close()


def test_cumulative_input_budget_pressure_after_six_diagnostics_still_submits_final_report(runtime, monkeypatch):
    """Regression for max_input_tokens being mistaken for a model failure."""
    from echo.agent import loop
    from echo.agent.budget import Budget
    from echo.agent.openai_client import LLMTurn
    from echo.agent.tools import ToolContext
    from echo.db.connections import analytics_conn, echo_conn, finance_conn
    from echo.ingest.scenarios import load_case

    setup = load_case("SCENARIO-02")
    finance, analytics, echo = finance_conn(), analytics_conn(), echo_conn()
    try:
        # Reproduce the observed pressure: six diagnostic turns total more
        # than the cumulative 12k application budget. The production Budget
        # reserves a larger final margin; this smaller margin makes the test
        # exercise the exact six-call boundary without an API request.
        class BoundaryBudget(Budget):
            def __init__(self):
                super().__init__()
                self.final_input_reserve = 1000

        monkeypatch.setattr(loop, "Budget", BoundaryBudget)
        final_args = {
            "title": "Observed numeric discrepancy",
            "summary": "The destination amount differs from the trusted source.",
            "observed_issue": "One persisted amount field differs.",
            "suspected_root_cause": "A numeric transformation is suspected from the observed ratio.",
            "supporting_evidence": ["The comparison recorded one source/destination mismatch."],
            "suspected_cause": "observed_numeric_transformation",
            "confidence": 0.8,
            "affected_record_ids": ["TX-000001"],
            "earliest_batch_id": None,
            "pipeline_safe_to_retry": True,
            "escalate": False,
            "uncertainty": [],
            "strategy": "restore",
            "safety_concerns": ["Deterministic safety checks must authorize repair."],
            "human_review_reason": None,
            "finding_summary": "One persisted amount field differs.",
            "evidence_summary": "The comparison recorded one source/destination mismatch.",
            "recommended_action": "Restore only the eligible field from trusted source evidence.",
        }

        class SixDiagnosticsThenFinal:
            model = "local-fixture"
            step = 0

            def next_turn(self, *, input_payload, previous_response_id):
                self.step += 1
                forced_final = "Final-report turn" in repr(input_payload)
                if not forced_final:
                    return LLMTurn(
                        "compare_records", {}, f"call-{self.step}", f"resp-{self.step}",
                        input_tokens=2100, output_tokens=20,
                        function_calls=[{"tool_name": "compare_records", "arguments": {}, "call_id": f"call-{self.step}"}],
                        response_status="completed",
                    )
                return LLMTurn(
                    "submit_investigation", final_args, "call-final", "resp-final",
                    input_tokens=100, output_tokens=100,
                    function_calls=[{"tool_name": "submit_investigation", "arguments": final_args, "call_id": "call-final"}],
                    response_status="completed",
                )

        monkeypatch.setattr(loop, "build_llm", lambda ctx: SixDiagnosticsThenFinal())
        result = loop.investigate(ToolContext(finance, analytics, echo, setup["incident_id"]))
        assert result["investigation_state"] == "complete"
        assert result["budget"]["tool_calls"] == 6
        assert result["budget"]["final_response_calls"] == 1
        assert result["budget"]["input_tokens"] == 12700
    finally:
        finance.close()
        analytics.close()
        echo.close()


def test_malformed_final_report_is_rejected_and_explained(runtime, monkeypatch):
    from echo.agent import loop
    from echo.agent.openai_client import LLMTurn
    from echo.agent.tools import ToolContext
    from echo.db.connections import analytics_conn, echo_conn, finance_conn
    from echo.ingest.scenarios import load_case

    setup = load_case("SCENARIO-02")
    finance, analytics, echo = finance_conn(), analytics_conn(), echo_conn()
    try:
        class MalformedFinal:
            model = "local-fixture"
            step = 0

            def next_turn(self, *, input_payload, previous_response_id):
                self.step += 1
                if self.step == 1:
                    return LLMTurn("compare_records", {}, "call-compare", "resp-compare", function_calls=[{"tool_name": "compare_records", "arguments": {}, "call_id": "call-compare"}], response_status="completed")
                if self.step == 2:
                    return LLMTurn("submit_investigation", {"confidence": 0.8, "strategy": "restore"}, "call-bad", "resp-bad", function_calls=[{"tool_name": "submit_investigation", "arguments": {"confidence": 0.8, "strategy": "restore"}, "call_id": "call-bad"}], response_status="completed")
                return LLMTurn(None, {}, None, "resp-message", raw_text="No structured report", response_status="completed")

        monkeypatch.setattr(loop, "build_llm", lambda ctx: MalformedFinal())
        result = loop.investigate(ToolContext(finance, analytics, echo, setup["incident_id"]))
        assert result["investigation_state"] == "incomplete"
        assert result["confidence"] is None
        invalid = echo.execute("SELECT payload_json FROM investigation_events WHERE incident_id=? AND kind='investigation_invalid'", (setup["incident_id"],)).fetchone()
        assert invalid is not None
        assert json.loads(invalid["payload_json"])["error"] == "invalid_investigation_response"
    finally:
        finance.close()
        analytics.close()
        echo.close()


def test_invalid_investigation_response_is_not_accepted():
    from types import SimpleNamespace

    from echo.agent.tools import submit_investigation

    ctx = SimpleNamespace(final=None)
    result = submit_investigation(ctx, suspected_cause="unknown", confidence=None, strategy="restore")
    assert result["accepted"] is False
    assert result["error"] == "invalid_investigation_response"
    assert ctx.final is None


def test_structured_investigation_report_is_accepted_with_unknown_confidence():
    from types import SimpleNamespace

    from echo.agent.tools import submit_investigation

    ctx = SimpleNamespace(final=None)
    result = submit_investigation(
        ctx,
        title="Observed field discrepancy",
        summary="The destination differs from the trusted source.",
        observed_issue="One supported field differs.",
        suspected_root_cause="Root cause not confirmed.",
        supporting_evidence=["One persisted comparison mismatch."],
        suspected_cause="unknown",
        confidence=None,
        safety_concerns=["Independent policy must decide whether repair is safe."],
        human_review_reason="Confidence is unavailable.",
        affected_record_ids=["R-1"],
        earliest_batch_id=None,
        pipeline_safe_to_retry=False,
        escalate=True,
        uncertainty=["No confirmed cause."],
        strategy="escalate",
        finding_summary="The destination differs from the trusted source.",
        evidence_summary="One persisted comparison mismatch.",
        recommended_action="Preserve the destination and review manually.",
    )
    assert result["accepted"] is True
    assert ctx.final["confidence"] is None


def test_openai_response_function_arguments_are_parsed_without_network_call():
    from types import SimpleNamespace

    from echo.agent.openai_client import OpenAILLM

    response = SimpleNamespace(
        id="resp-local",
        status="completed",
        usage=SimpleNamespace(input_tokens=12, output_tokens=8),
        output=[SimpleNamespace(type="function_call", name="submit_investigation", call_id="call-local", arguments='{"confidence": 0.8, "strategy": "escalate"}')],
        output_text=None,
    )

    class Responses:
        def create(self, **kwargs):
            return response

    client = OpenAILLM.__new__(OpenAILLM)
    client.model = "local-fixture"
    client.client = SimpleNamespace(responses=Responses())
    turn = client.next_turn(input_payload=[], previous_response_id=None)
    assert turn.tool_name == "submit_investigation"
    assert turn.arguments["confidence"] == 0.8
    assert turn.response_status == "completed"


def test_openai_response_preserves_all_function_calls():
    from types import SimpleNamespace

    from echo.agent.openai_client import OpenAILLM

    response = SimpleNamespace(
        id="resp-multi",
        status="completed",
        usage=SimpleNamespace(input_tokens=5, output_tokens=5),
        output=[
            SimpleNamespace(type="function_call", name="compare_records", call_id="call-a", arguments="{}"),
            SimpleNamespace(type="function_call", name="profile_text", call_id="call-b", arguments="{}"),
        ],
        output_text=None,
    )

    class Responses:
        def create(self, **kwargs):
            return response

    client = OpenAILLM.__new__(OpenAILLM)
    client.model = "local-fixture"
    client.client = SimpleNamespace(responses=Responses())
    turn = client.next_turn(input_payload=[], previous_response_id=None)
    assert [call["call_id"] for call in turn.function_calls] == ["call-a", "call-b"]


def test_no_tool_response_is_incomplete_not_zero_confidence(runtime, monkeypatch):
    from echo.agent import loop
    from echo.agent.openai_client import LLMTurn
    from echo.agent.tools import ToolContext
    from echo.db.connections import analytics_conn, echo_conn, finance_conn
    from echo.ingest.scenarios import load_case

    setup = load_case("SCENARIO-03")
    finance, analytics, echo = finance_conn(), analytics_conn(), echo_conn()
    try:
        class NoSubmit:
            model = "local-fixture"

            def next_turn(self, *, input_payload, previous_response_id):
                return LLMTurn(None, {}, None, "resp-local", raw_text="not a tool call", response_status="completed")

        monkeypatch.setattr(loop, "build_llm", lambda ctx: NoSubmit())
        result = loop.investigate(ToolContext(finance, analytics, echo, setup["incident_id"]))
        assert result["investigation_state"] == "incomplete"
        assert result["confidence"] is None
        assert result["escalate"] is True
    finally:
        finance.close()
        analytics.close()
        echo.close()


def test_live_client_uses_bounded_timeout_and_no_sdk_retries(monkeypatch):
    import sys
    from types import SimpleNamespace

    from echo.agent.openai_client import OpenAILLM

    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    OpenAILLM(model="local-fixture")
    assert captured["timeout"] > 0
    assert captured["max_retries"] == 0


@pytest.mark.parametrize("status_code", [401, 429])
def test_live_api_auth_and_quota_errors_are_not_silently_mocked(status_code):
    from types import SimpleNamespace

    from echo.agent.openai_client import OpenAILLM

    class APIError(Exception):
        def __init__(self):
            super().__init__(f"HTTP {status_code}")
            self.status_code = status_code

    class Responses:
        def create(self, **kwargs):
            raise APIError()

    client = OpenAILLM.__new__(OpenAILLM)
    client.model = "local-fixture"
    client.client = SimpleNamespace(responses=Responses())
    with pytest.raises(APIError):
        client.next_turn(input_payload=[], previous_response_id=None)


def test_malformed_function_arguments_raise_for_explicit_error_handling():
    from types import SimpleNamespace

    from echo.agent.openai_client import OpenAILLM

    response = SimpleNamespace(
        id="resp-malformed",
        status="completed",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        output=[SimpleNamespace(type="function_call", name="compare_records", call_id="call-bad", arguments="not-json")],
        output_text=None,
    )

    class Responses:
        def create(self, **kwargs):
            return response

    client = OpenAILLM.__new__(OpenAILLM)
    client.model = "local-fixture"
    client.client = SimpleNamespace(responses=Responses())
    with pytest.raises(ValueError):
        client.next_turn(input_payload=[], previous_response_id=None)
