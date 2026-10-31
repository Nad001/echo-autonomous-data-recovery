from __future__ import annotations

import argparse
import json
import time

from echo.agent.loop import investigate
from echo.agent.budget import Budget
from echo.agent.tools import ToolContext
from echo.db.connections import analytics_conn, echo_conn, finance_conn
from echo.notify.service import emit_activity
from echo.recovery.executor import apply_repairs
from echo.recovery.policy import evaluate_plan
from echo.recovery.quarantine import quarantine_pipeline
from echo.recovery.verifier import verify_incident
from echo.worker.queue import claim_job, finish_job


def process_one() -> dict | None:
    echo = echo_conn()
    job = claim_job(echo)
    if job is None:
        echo.close()
        return None
    finance, analytics = finance_conn(), analytics_conn()
    incident_id = job["incident_id"]
    try:
        incident = echo.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if incident is None:
            raise RuntimeError(f"incident not found: {incident_id}")
        ctx = ToolContext(finance, analytics, echo, incident_id)
        intent = investigate(ctx)
        echo.execute("INSERT INTO usage_events(incident_id, model, input_tokens, output_tokens, estimated_usd, ts) VALUES (?,?,?,?,?,datetime('now'))", (incident_id, intent["budget"]["model"], intent["budget"]["input_tokens"], intent["budget"]["output_tokens"], intent["budget"]["estimated_usd"]))
        pipeline_id = incident["pipeline_id"]
        requested = intent.get("affected_record_ids") or None
        plan = evaluate_plan(
            finance,
            analytics,
            echo,
            incident_id=incident_id,
            pipeline_id=pipeline_id,
            requested_ids=requested,
            investigation_confidence=intent.get("confidence"),
            investigation_complete=(
                intent.get("investigation_state") == "complete"
                and bool(intent.get("model_submitted", True))
                and not bool(intent.get("investigation_error"))
            ),
        )
        # ``pipeline_safe_to_retry`` describes whether repeating this
        # particular operation is advisable; it is not proof that the
        # configured pipeline itself is defective. Only the deterministic
        # plan's pipeline diagnosis can quarantine the pipeline.
        if plan["pipeline_faulty"]:
            quarantine_pipeline(echo, pipeline_id, incident_id, "Active transformation defect; retry is unsafe")
        # The policy's auto_execute decision is authoritative. This also
        # prevents a capped or otherwise incomplete plan from partially
        # repairing a full-scope corruption incident.
        # The investigator's ``escalate`` field is advisory language about
        # uncertainty or the suspected mechanism.  It must not override the
        # deterministic recovery policy: a safe, complete, source-backed plan
        # may proceed even when the model recommends review of the underlying
        # cause.  Genuine conflicts, incomplete investigations, low
        # confidence, stale evidence, or failed policy checks are represented
        # by the plan/safety fields below and remain blocked.
        if plan["unsafe_count"] or not plan["executable_items"] or not plan.get("safety", {}).get("auto_execute"):
            outcome = {"status": "escalated", "intent": intent, "plan": plan}
            echo.execute("UPDATE incidents SET investigation_status='completed', recovery_status='escalated', review_required=1, outcome_json=? WHERE id=?", (json.dumps(outcome), incident_id))
            emit_activity(echo, "escalation_created", "Recovery requires human review", incident_id=incident_id)
            echo.commit()
        else:
            applied = apply_repairs(analytics, echo, incident_id=incident_id, items=plan["executable_items"])
            verification = verify_incident(finance, analytics, echo, incident_id=incident_id, pipeline_id=pipeline_id, executed_ids={i["record_id"] for i in plan["executable_items"]})
            outcome = {"status": verification["recovery_status"], "intent": intent, "plan": plan, "applied": applied, "verification": verification}
            echo.execute("UPDATE incidents SET investigation_status='completed', outcome_json=? WHERE id=?", (json.dumps(outcome), incident_id))
            echo.commit()
        finish_job(echo, job["id"])
        return {"incident_id": incident_id, "outcome": outcome}
    except Exception as exc:
        # Preserve response usage even when the investigation fails before it
        # returns an intent to the worker. This is metadata only; it never
        # retries the request and never stores credentials.
        response_rows = echo.execute(
            "SELECT payload_json FROM investigation_events WHERE incident_id=? AND kind='model_response'",
            (incident_id,),
        ).fetchall()
        input_tokens = output_tokens = 0
        for response_row in response_rows:
            try:
                payload = json.loads(response_row["payload_json"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            input_tokens += int(payload.get("input_tokens") or 0)
            output_tokens += int(payload.get("output_tokens") or 0)
        model_row = echo.execute(
            "SELECT payload_json FROM investigation_events WHERE incident_id=? AND kind='investigation_started' ORDER BY id LIMIT 1",
            (incident_id,),
        ).fetchone()
        model = "unknown"
        if model_row:
            try:
                model = json.loads(model_row["payload_json"] or "{}").get("model") or model
            except json.JSONDecodeError:
                pass
        if response_rows and not echo.execute("SELECT 1 FROM usage_events WHERE incident_id=? LIMIT 1", (incident_id,)).fetchone():
            usage_budget = Budget()
            usage_budget.add_usage(input_tokens, output_tokens)
            echo.execute(
                "INSERT INTO usage_events(incident_id, model, input_tokens, output_tokens, estimated_usd, ts) VALUES (?,?,?,?,?,datetime('now'))",
                (incident_id, model, input_tokens, output_tokens, usage_budget.estimated_usd(model)),
            )
        # A failed investigation is not a recovery failure and must never be
        # interpreted as permission to repair. Preserve the error as failed
        # investigation evidence while routing the unresolved case to review.
        echo.execute(
            "UPDATE incidents SET investigation_status='failed', recovery_status='escalated', review_required=1, outcome_json=? WHERE id=?",
            (json.dumps({"status": "investigation_failed", "error": str(exc)}), incident_id),
        )
        emit_activity(echo, "escalation_created", "Investigation failed; human review required", incident_id=incident_id)
        echo.commit()
        finish_job(echo, job["id"], error=str(exc))
        return {"incident_id": incident_id, "error": str(exc)}
    finally:
        finance.close()
        analytics.close()
        echo.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ECHO incident worker")
    parser.add_argument("--once", action="store_true", help="process one queued job and exit")
    args = parser.parse_args()
    while True:
        result = process_one()
        if result:
            print(json.dumps(result, indent=2))
        if args.once or result is None:
            return
        time.sleep(0.2)
