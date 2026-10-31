from __future__ import annotations

import json
import re
import time
from typing import Any

from echo.agent.budget import Budget
from echo.agent.openai_client import build_llm
from echo.agent.prompts import SYSTEM_PROMPT
from echo.agent.tools import ToolContext, build_evidence_package, compare_records, execute_tool


def investigate(ctx: ToolContext) -> dict[str, Any]:
    """Run the bounded investigation loop and return the model's structured intent.

    The model can only select registered tools. Database mutation is deliberately
    outside this loop; recovery policy and verification own that responsibility.
    """
    budget = Budget()
    llm = build_llm(ctx)
    previous_response_id: str | None = None
    observed = compare_records(ctx)
    context = build_evidence_package(ctx)
    context["incident_id"] = ctx.incident_id
    payload: Any = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Investigate the selected incident using this observed source/destination evidence package. It contains no hidden scenario answer: {json.dumps(context, separators=(',', ':'))}"},
    ]
    started = time.monotonic()
    completion_reason: str | None = None
    final_turn_reserved = False
    ctx.echo.execute(
        "UPDATE incidents SET investigation_status='investigating' WHERE id=?",
        (ctx.incident_id,),
    )
    ctx.record_event("investigation_started", "Investigation started", {"model": llm.model})

    while budget.diagnostics_remaining_ok(llm.model) or final_turn_reserved:
        # A single Responses message may contain many diagnostic calls. All
        # of them must receive outputs, even when they fill the diagnostic
        # budget; otherwise the provider rejects the next request because a
        # function_call_output is missing. Reserve one follow-up turn solely
        # for the structured final interpretation.
        attempted_final = final_turn_reserved
        if final_turn_reserved:
            final_turn_reserved = False
        request_payload = payload
        if attempted_final:
            request_payload = payload + [{
                "role": "user",
                "content": "Final-report turn: stop diagnostic exploration and submit the complete validated submit_investigation report now. Use only the evidence already returned.",
            }]
        try:
            turn = llm.next_turn(input_payload=request_payload, previous_response_id=previous_response_id)
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code is None:
                match = re.search(r"\b([45]\d\d)\b", str(exc))
                status_code = int(match.group(1)) if match else None
            ctx.record_event(
                "investigation_error",
                "Investigation request failed",
                {"error_type": type(exc).__name__, "error": str(exc), "http_status": status_code, "model": llm.model, "tool_calls": budget.tool_calls},
            )
            raise
        calls = turn.function_calls or [{"tool_name": turn.tool_name, "arguments": turn.arguments, "call_id": turn.call_id}]
        has_final_call = any(call["tool_name"] == "submit_investigation" for call in calls)
        diagnostic_call_count = sum(1 for call in calls if call["tool_name"] != "submit_investigation")
        budget.tool_calls += diagnostic_call_count
        if has_final_call:
            budget.final_response_calls += sum(1 for call in calls if call["tool_name"] == "submit_investigation")
        budget.add_usage(turn.input_tokens, turn.output_tokens)
        previous_response_id = turn.response_id
        ctx.record_event(
            "model_response",
            "Model response received",
            {
                "response_id": turn.response_id,
                "tool_name": turn.tool_name,
                "tool_names": [call["tool_name"] for call in calls],
                "function_call_count": len(calls),
                "input_tokens": turn.input_tokens,
                "output_tokens": turn.output_tokens,
                "has_text": bool(turn.raw_text),
                "raw_text": turn.raw_text if turn.tool_name is None else None,
                "response_status": turn.response_status,
            },
        )
        if turn.tool_name is None:
            completion_reason = "model_returned_no_tool_call"
            ctx.record_event("model_message", "Model returned no tool call", {"text": turn.raw_text or ""})
            break
        outputs = []
        submitted = False
        for call in calls:
            tool_name = call["tool_name"]
            result = execute_tool(ctx, tool_name, call["arguments"])
            if tool_name == "submit_investigation":
                if result.get("accepted"):
                    submitted = True
                    break
                completion_reason = result.get("error", "invalid_investigation_response")
                ctx.record_event("investigation_invalid", "Investigation response was rejected", result)
            outputs.append({
                "type": "function_call_output",
                "call_id": call["call_id"] or f"call-{budget.tool_calls}",
                "output": json.dumps(result, separators=(",", ":")),
            })
        if submitted:
            break
        payload = outputs
        if not has_final_call and (budget.tool_calls >= budget.max_tool_calls or budget.should_reserve_final()):
            final_turn_reserved = True
        elif has_final_call and not submitted and budget.final_response_calls < budget.max_final_response_calls and budget.remaining_ok(llm.model):
            # One correction is allowed for a malformed structured report,
            # but only while the cumulative application budget still permits
            # another request. No fallback report is fabricated.
            final_turn_reserved = True
        elif attempted_final and not submitted:
            completion_reason = completion_reason or "final_report_not_submitted"
            break

    if ctx.final is None:
        reason = completion_reason or budget.reason(llm.model) or "model_did_not_submit"
        ctx.final = {
            "suspected_cause": "investigation_incomplete",
            "confidence": None,
            "affected_record_ids": [],
            "earliest_batch_id": None,
            "pipeline_safe_to_retry": False,
            "escalate": True,
            "uncertainty": [reason],
            "strategy": "escalate",
            "investigation_state": "incomplete",
            "failure_reason": reason,
            "model_submitted": False,
        }
    else:
        ctx.final.setdefault("investigation_state", "complete")
        ctx.final.setdefault("model_submitted", True)
    result = dict(ctx.final)
    result["budget"] = {
        "tool_calls": budget.tool_calls,
        "final_response_calls": budget.final_response_calls,
        "total_tool_calls": budget.tool_calls + budget.final_response_calls,
        "input_tokens": budget.input_tokens,
        "output_tokens": budget.output_tokens,
        "estimated_usd": budget.estimated_usd(llm.model),
        "max_estimated_usd": budget.max_estimated_usd,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "model": llm.model,
    }
    ctx.record_event("investigation_submitted", "Investigation intent submitted", result)
    return result
