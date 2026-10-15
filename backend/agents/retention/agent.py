"""Retention agent: spots customers who may not renew and picks the next step.

The LLM rates lapse risk and chooses one intervention, channel and (for a retention offer) a
discount, all constrained to what the renewal rules allow. An extra-cover choice is turned
into a concrete offer by the recommendation agent.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from backend.agents.retention.decision import decide_lapse
from backend.agents.shared.node import BAND_PRIORITY, node
from backend.agents.state import GraphState, deps
from backend.enums import Action, Priority
from backend.services.rules.renewal import RenewalState
from backend.services.rules.routing import route_queue
from backend.utils.audit import audit


@node("retention")
async def retention(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    a, f = state["assessment"], state["renewal_facts"]
    decision = await decide_lapse(
        d.llm, signals=state["signals"], assessment=a, preferred_channel=f.preferred_channel
    )

    priority = Priority(BAND_PRIORITY[decision.band])
    if a.state in (RenewalState.IN_GRACE, RenewalState.LAPSED):
        priority = Priority.HIGH  # cover at risk now

    offer = None
    if decision.intervention == Action.RETENTION_OFFER and decision.discount_pct:
        new_premium = round(f.premium * (100 - decision.discount_pct) / 100)
        offer = {
            "type": "discount",
            "discount_pct": decision.discount_pct,
            "max_discount_pct": a.max_discount_pct,
            "premium_before": f.premium,
            "premium_after": new_premium,
        }
    queue = route_queue(
        decision.intervention, f.channel_owner, regulated_product=f.product_regulated
    )
    forced = (
        [f"LLM flagged: {decision.review_reason or 'no reason given'}"]
        if decision.needs_review
        else []
    )
    await audit(
        d.db,
        "node.retention",
        {
            "band": decision.band,
            "confidence": decision.confidence,
            "intervention": decision.intervention,
            "channel": decision.channel,
            "discount_pct": decision.discount_pct,
            "queue": queue,
        },
        subject_type="policy",
        subject_id=state["subject_id"],
    )
    return {
        "decisions": {"lapse_risk": decision.model_dump(mode="json")},
        "action": decision.intervention,
        "channel": decision.channel,
        "offer": offer,
        "band": decision.band,
        "confidence": decision.confidence.value,
        "priority": priority.value,
        "queue": queue.value,
        "explanation": decision.rationale,
        "forced_review": forced,
    }
