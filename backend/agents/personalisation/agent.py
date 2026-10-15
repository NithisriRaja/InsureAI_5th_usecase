"""Personalisation agent: drafts the message for the chosen next step (LLM).

Internal tasks get no message.

Customer-facing channels get a customer message; ``intermediary`` gets a task note for the
broker / employer contact who owns the relationship. Each draft sees only the facts its
intervention needs (a payment reminder never sees renewal pricing, and so on).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig

from backend import rulebook
from backend.agents.personalisation.decision import draft_message, render
from backend.agents.shared.node import node
from backend.agents.state import GraphState, deps
from backend.config import get_settings
from backend.enums import Action, Channel, ChannelOwner
from backend.services.rules.facts import RenewalFacts
from backend.services.rules.renewal import RenewalAssessment, is_expiry
from backend.utils.audit import audit

SIGN_OFF = {
    ChannelOwner.ADVISER: "Your financial adviser",
    ChannelOwner.DIRECT: "Your insurance team",
}
INTERMEDIARY_SIGN_OFF = "Insurer operations team"


def _money(minor: int) -> str:
    return f"{minor / 100:,.2f} {get_settings().currency}"


def message_facts(
    action: str, f: RenewalFacts, a: RenewalAssessment, offer: dict[str, Any] | None
) -> dict[str, Any]:
    line = rulebook.LINES.get(f.line, {}).get("label", f.line)
    facts: dict[str, Any] = {
        "product": f.product_name,
        "line": line,
        "cover_state": a.state.value,
        "premium_period": f.payment_frequency,
    }
    if action in (Action.REMINDER, Action.RETENTION_OFFER, Action.SERVICE_FOLLOW_UP) and is_expiry(
        f
    ):
        facts |= {
            "end_date": f.end_date.isoformat(),
            "days_to_expiry": a.signals["days_to_expiry"],
            "current_annual_premium": _money(f.prev_premium),
            "renewal_annual_premium": _money(f.premium),
            "premium_change_pct": a.signals["premium_change_pct"],
        }
        if offer and offer.get("type") == "discount":
            # Name the pre-discount price only when there is a discount: the key name alone
            # makes the model write "before discount" in messages that offer none.
            facts["renewal_annual_premium_before_discount"] = facts.pop("renewal_annual_premium")
            facts["renewal_annual_premium_after_discount"] = _money(offer["premium_after"])
            facts["annual_saving"] = _money(f.premium - offer["premium_after"])
    if action in (Action.PAYMENT_REMINDER, Action.REINSTATEMENT) and f.overdue_amount:
        facts["amount_overdue"] = _money(f.overdue_amount)
        if f.oldest_overdue_due:
            facts["overdue_since"] = f.oldest_overdue_due.isoformat()
            facts["grace_period_ends"] = (
                f.oldest_overdue_due + timedelta(days=f.product_grace_days)
            ).isoformat()
    if action == Action.REINSTATEMENT and is_expiry(f):
        facts |= {"ended_on": f.end_date.isoformat(), "renewal_annual_premium": _money(f.premium)}
    if action == Action.DOCUMENT_REQUEST:
        facts["documents_outstanding"] = f.docs_outstanding
    if action == Action.PLAN_REVIEW:
        for t in a.triggers:
            if t.type.value == "milestone":
                facts["milestone"] = f.milestone_label
                facts["milestone_date"] = f.milestone_date.isoformat() if f.milestone_date else None
            if t.type.value == "scheduled_review":
                facts["review_due_date"] = t.date.isoformat() if t.date else None
    if action == Action.ADD_ON_OFFER and offer and offer.get("type") == "add_on":
        cand = next((c for c in f.add_on_candidates if c.code == offer["code"]), None)
        facts["additional_cover"] = cand.name if cand else offer["name"]
        facts["additional_cover_summary"] = cand.description if cand else ""
    return facts


@node("personalisation")
async def personalisation(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    action, channel = state["action"], state["channel"]
    if action == Action.INTERNAL_TASK or channel == Channel.INTERNAL:
        await audit(
            d.db,
            "node.personalisation",
            {"drafted": False, "reason": "internal task"},
            subject_type="policy",
            subject_id=state["subject_id"],
        )
        return {"draft_message": None, "draft_subject": None}

    f, a, offer = state["renewal_facts"], state["assessment"], state.get("offer")
    sign_off = (
        INTERMEDIARY_SIGN_OFF
        if channel == Channel.INTERMEDIARY
        else SIGN_OFF.get(f.channel_owner, SIGN_OFF[ChannelOwner.DIRECT])
    )
    facts = message_facts(action, f, a, offer)
    draft = await draft_message(
        d.llm,
        channel=channel,
        intervention=action,
        facts=facts,
        discount_pct=offer["discount_pct"] if offer and offer.get("type") == "discount" else None,
        sign_off=sign_off,
    )
    await audit(
        d.db,
        "node.personalisation",
        {"drafted": True, "channel": channel, "chars": len(draft.body)},
        subject_type="policy",
        subject_id=state["subject_id"],
    )
    return {
        "draft_subject": render(draft.subject, state.get("first_name")),
        "draft_message": render(draft.body, state.get("first_name")),
        "decisions": {"message_draft": draft.model_dump(mode="json")},
    }
