"""Workflow agent: turns the agents' work into a follow-up task waiting for approval.

Composes the recommendation (reminder, document request, offer, ...) and stores it as
``pending_approval`` in one transaction, superseding any older open one for the same event.
Every recommendation passes the code-level guardrails first. After a human approves it, the
message is delivered by ``workflow.delivery``. Renewal skips produce no recommendation.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from backend import rulebook
from backend.agents.shared.node import node
from backend.agents.shared.review import needs_review
from backend.agents.state import GraphState, deps
from backend.agents.workflow.links import action_link
from backend.db.models import Recommendation
from backend.db.repositories import audit as audit_repo
from backend.enums import RecStatus
from backend.services import guardrails
from backend.utils.audit import audit
from backend.utils.clock import utcnow
from backend.utils.context import current_run_id
from backend.utils.ids import new_id


@node("workflow")
async def workflow(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    if state.get("gate") == "skip":
        await audit(
            d.db,
            "run.skipped",
            {"reason": state.get("skip_reason")},
            subject_type=state["subject_type"],
            subject_id=state["subject_id"],
        )
        return {"recommendation_id": None}

    confidences = [
        v.get("confidence") for v in (state.get("decisions") or {}).values() if isinstance(v, dict)
    ]
    review, review_reasons = needs_review(
        llm_flag=False,
        llm_reason=None,
        confidences=confidences,
        forced=state.get("forced_review", []),
    )
    now = utcnow()
    policy = await d.policy_admin.get_policy(state["subject_id"])
    link = (
        action_link(str(state["action"]), state.get("channel"), policy.policy_number)
        if policy and state.get("draft_message")
        else None
    )

    rec = Recommendation(
        id=new_id("rec"),
        run_id=state.get("run_id") or current_run_id.get(),
        use_case=state["use_case"],
        subject_type=state["subject_type"],
        subject_id=state["subject_id"],
        cycle_key=state["cycle_key"],
        status=RecStatus.PENDING_APPROVAL.value,
        queue=str(state["queue"]),
        priority=str(state["priority"]),
        action=str(state["action"]),
        channel_owner=state.get("channel_owner"),
        lifecycle_type=state.get("lifecycle_type"),
        triggers=state.get("triggers") or [],
        rulebook_version=rulebook.RULEBOOK_VERSION,
        band=state.get("band"),
        confidence=state.get("confidence"),
        needs_review=review,
        review_reasons=review_reasons,
        signals=state.get("signals") or {},
        decisions=state.get("decisions") or {},
        rule_results=state.get("rule_results") or [],
        offer=state.get("offer"),
        cover_suggestion=state.get("cover_suggestion"),
        channel=state.get("channel"),
        link=link,
        draft_subject=state.get("draft_subject"),
        draft_message=state.get("draft_message"),
        explanation=state.get("explanation"),
        fairness=state.get("fairness") or {},
        expires_at=state.get("expires_at"),
        created_at=now,
    )
    try:
        guardrails.check_recommendation(
            {
                "action": rec.action,
                "channel": rec.channel,
                "channel_owner": rec.channel_owner,
                "offer": rec.offer,
                "status": rec.status,
            }
        )
    except guardrails.GuardrailViolation as e:
        await audit(
            d.db,
            "guardrail.blocked",
            {"rule": e.rule, "error": str(e), "action": rec.action, "channel": rec.channel},
            subject_type=rec.subject_type,
            subject_id=rec.subject_id,
        )
        raise

    async with d.db.session() as s:
        old_ids = []
        for old in s.where(
            Recommendation,
            lambda r: r.subject_type == rec.subject_type
            and r.subject_id == rec.subject_id
            and r.cycle_key == rec.cycle_key
            and r.status == RecStatus.PENDING_APPROVAL,
        ):
            old.status = RecStatus.SUPERSEDED.value
            old.version += 1
            old_ids.append(old.id)
        s.add(rec)
        for old in old_ids:
            audit_repo.add_event(
                s,
                event_type="recommendation.superseded",
                run_id=rec.run_id,
                recommendation_id=old,
                subject_type=rec.subject_type,
                subject_id=rec.subject_id,
                node="workflow",
                payload={"superseded_by": rec.id},
            )
        audit_repo.add_event(
            s,
            event_type="recommendation.created",
            run_id=rec.run_id,
            recommendation_id=rec.id,
            subject_type=rec.subject_type,
            subject_id=rec.subject_id,
            node="workflow",
            payload={
                "action": rec.action,
                "queue": rec.queue,
                "priority": rec.priority,
                "channel_owner": rec.channel_owner,
                "needs_review": rec.needs_review,
                "rulebook_version": rec.rulebook_version,
                "superseded": old_ids,
            },
        )
    return {"recommendation_id": rec.id}
