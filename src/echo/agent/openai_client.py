from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from echo.config import LLM_MODE, MAX_OUTPUT_TOKENS, MAX_SECONDS, OPENAI_API_KEY, OPENAI_MODEL
from echo.agent.tools import OPENAI_TOOLS, ToolContext, compare_records, inspect_incident, inspect_pipeline_configuration, profile_text, propose_recovery, test_hypothesis
from echo.compare import field_mismatches


@dataclass
class LLMTurn:
    tool_name: str | None
    arguments: dict
    call_id: str | None
    response_id: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    raw_text: str | None = None
    response_status: str | None = None
    function_calls: list[dict[str, Any]] | None = None


class LLMClient(Protocol):
    model: str

    def next_turn(self, *, input_payload: Any, previous_response_id: str | None) -> LLMTurn: ...


class HeuristicLLM:
    """Evidence-driven stand-in for tests. Never receives scenario labels."""

    model = "heuristic-mock"

    def __init__(self, ctx: ToolContext) -> None:
        self.ctx = ctx
        self.step = 0
        self.state: dict[str, Any] = {}

    def next_turn(self, *, input_payload: Any, previous_response_id: str | None) -> LLMTurn:
        self.step += 1
        if self.step == 1:
            return LLMTurn("inspect_incident", {}, "call-1", "mock-1")
        if self.step == 2:
            return LLMTurn("inspect_sync_run", {"run_id": self.state.get("run_id") or self._run_id()}, "call-2", "mock-2")
        if self.step == 3:
            return LLMTurn("profile_text" if self._is_text_case() else "profile_fields", {}, "call-3", "mock-3")
        if self.step == 4:
            return LLMTurn("test_hypothesis", {"hypothesis": "text_truncation" if self._is_text_case() else "amount_scale"}, "call-4", "mock-4")
        if self.step == 5:
            return LLMTurn("test_hypothesis", {"hypothesis": "text_replacement" if self._is_text_case() else "transform_mismatch"}, "call-5", "mock-5")
        if self.step == 6:
            sample = compare_records(self.ctx).get("affected_record_ids_sample") or []
            return LLMTurn("inspect_record_history", {"record_ids": sample[:8]}, "call-6", "mock-6")
        if self.step == 7:
            return self._final_turn("call-7", "mock-7")
        return self._final_turn(f"call-{self.step}", f"mock-{self.step}")

    def _is_text_case(self) -> bool:
        return bool({row.get("field") for row in field_mismatches(self.ctx.finance, self.ctx.analytics)} - {"amount_halalas"})

    def _final_turn(self, call_id: str, response_id: str) -> LLMTurn:
        plan = propose_recovery(self.ctx)
        pipe = inspect_pipeline_configuration(self.ctx)
        cmp = compare_records(self.ctx)
        escalate = bool(plan.get("unsafe_count")) or plan.get("decision") == "escalate"
        strategy = "escalate" if escalate else ("quarantine_and_restore" if pipe.get("remains_faulty") else "restore")
        cause = "unknown"
        text_case = self._is_text_case()
        text_profile = profile_text(self.ctx) if text_case else {}
        if pipe.get("remains_faulty"):
            cause = "persistent_transform_defect"
        elif plan.get("unsafe_count"):
            cause = "unsafe_or_ambiguous_destination_state"
        elif text_case:
            change_types = text_profile.get("change_type_counts") or {}
            cause = "text_truncation" if change_types.get("truncation") else "text_replacement"
        elif test_hypothesis(self.ctx, "amount_scale").get("supported"):
            cause = "silent_amount_scale_corruption"
        else:
            cause = "observed_field_transformation"
        fields = cmp.get("fields") or []
        affected = cmp.get("affected_record_ids") or []
        evidence = [
            f"{cmp.get('mismatch_count', 0)} persisted field discrepancy(ies) were found.",
            f"Affected fields: {', '.join(fields) if fields else 'none recorded'}.",
            f"Affected records are bounded to {len(affected)} identifier(s) in the investigation package.",
        ]
        summary = f"The destination differs from the trusted source in {len(fields)} field(s) across {len(affected)} recorded affected identifier(s)."
        if text_case:
            summary = f"Text fields differ between the destination and trusted source across {len(affected)} recorded affected identifier(s)."
        payload = {
            "title": f"Observed synchronization discrepancy in {', '.join(fields) if fields else 'supported fields'}",
            "summary": summary,
            "observed_issue": summary,
            "suspected_root_cause": cause.replace("_", " "),
            "supporting_evidence": evidence,
            "suspected_cause": cause,
            "confidence": 0.85 if fields else None,
            "affected_record_ids": affected,
            "earliest_batch_id": None,
            "pipeline_safe_to_retry": not bool(pipe.get("remains_faulty")),
            "escalate": escalate,
            "uncertainty": [],
            "strategy": strategy,
            "safety_concerns": ["Deterministic policy and independent verification must authorize and validate any repair."],
            "human_review_reason": None if not escalate else "The evidence or safety policy does not authorize automatic recovery.",
            "finding_summary": summary,
            "evidence_summary": " ".join(evidence),
            "recommended_action": "Restore only eligible affected fields from trusted source evidence." if not escalate else "Preserve the destination and route the incident for human review.",
        }
        return LLMTurn("submit_investigation", payload, call_id, response_id)

    def _run_id(self) -> str:
        incident = inspect_incident(self.ctx)
        self.state["run_id"] = incident.get("run_id")
        return incident.get("run_id") or ""


class ScriptedLLM:
    model = "scripted-mock"

    def __init__(self, calls: list[tuple[str, dict]]) -> None:
        self.calls = calls
        self.index = 0

    def next_turn(self, *, input_payload: Any, previous_response_id: str | None) -> LLMTurn:
        if self.index >= len(self.calls):
            raise RuntimeError("scripted LLM exhausted")
        name, args = self.calls[self.index]
        self.index += 1
        return LLMTurn(name, args, f"script-{self.index}", f"script-resp-{self.index}")


class OpenAILLM:
    def __init__(self, model: str | None = None) -> None:
        from openai import OpenAI

        self.model = model or OPENAI_MODEL
        # Keep one bounded request per investigation. The SDK's default retry
        # behavior could otherwise repeat a paid request after a transient error
        # and outlive ECHO's own investigation budget.
        self.client = OpenAI(api_key=OPENAI_API_KEY, timeout=MAX_SECONDS, max_retries=0)

    def next_turn(self, *, input_payload: Any, previous_response_id: str | None) -> LLMTurn:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "tools": OPENAI_TOOLS,
            "input": input_payload,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
        }
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id
        # Live mode is intentionally fail-fast. A network, authentication,
        # quota, or model error must be visible to the operator; it must never
        # silently turn a paid investigation into a mock investigation.
        response = self.client.responses.create(**kwargs)
        usage = getattr(response, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        function_calls = []
        for item in response.output or []:
            if getattr(item, "type", None) == "function_call":
                args = item.arguments
                parsed = json.loads(args) if isinstance(args, str) else (args or {})
                function_calls.append({
                    "tool_name": item.name,
                    "arguments": parsed,
                    "call_id": getattr(item, "call_id", None),
                })
        if function_calls:
            first = function_calls[0]
            return LLMTurn(
                first["tool_name"],
                first["arguments"],
                first["call_id"],
                response.id,
                in_tok,
                out_tok,
                response_status=getattr(response, "status", None),
                function_calls=function_calls,
            )
        text = getattr(response, "output_text", None)
        return LLMTurn(None, {}, None, response.id, in_tok, out_tok, raw_text=text, response_status=getattr(response, "status", None))


def build_llm(ctx: ToolContext) -> LLMClient:
    if LLM_MODE == "mock":
        return HeuristicLLM(ctx)
    if LLM_MODE == "openai":
        if not OPENAI_API_KEY:
            raise RuntimeError("Live OpenAI mode requires OPENAI_API_KEY in the project-root .env file")
        return OpenAILLM()
    raise RuntimeError(f"Unsupported investigation mode: {LLM_MODE}")
