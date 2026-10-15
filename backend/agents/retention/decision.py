"""Lapse-risk band + intervention choice from the rule-computed allowed set."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.agents.shared.decision import (
    REASON_GUIDE,
    Confidence,
    Reason,
    grounding_errors,
    score_band_errors,
)
from backend.enums import Action, Channel
from backend.services.llm.client import LLMClient
from backend.services.rules.renewal import RenewalAssessment, validate_intervention

PURPOSE = "lapse_risk"
BAND_RANGES = {"high": (0.6, 1.0), "medium": (0.3, 0.7), "low": (0.0, 0.4)}


class LapseDecision(BaseModel):
    band: Literal["high", "medium", "low"]
    score: float = Field(ge=0, le=1)
    confidence: Confidence
    reasons: list[Reason] = Field(min_length=1, max_length=5)
    intervention: str
    channel: Literal["email", "sms", "email_sms", "internal", "intermediary"]
    discount_pct: float | None = Field(
        default=None, description="Only for retention_offer; must not exceed max_discount_pct."
    )
    rationale: str = Field(
        max_length=500, description="1-2 crisp sentences: why this step, why now."
    )
    needs_review: bool
    review_reason: str | None = Field(default=None, max_length=300)


INSTRUCTIONS = f"""
You are a retention analyst at an insurer. Estimate how likely this policy is to stop (lapse,
not renew or not continue premiums): high, medium or low. The lifecycle_type tells you how the
policy stays in force (expiry_renewal / group_scheme_renewal = renewed at the end of a term;
premium_continuation / milestone / scheduled_review = stays in force while premiums are paid
and is reviewed periodically). The triggers are the events that need attention now.
Then choose the single best intervention from allowed_actions, the channel from the allowed
channels for that action, and:
- only for retention_offer, a discount_pct no larger than max_discount_pct (smallest likely to
  work);
- add_on_offer only when add_on_options is not empty (the recommendation agent then picks
  the cover).
Channel rules: service actions (reminder, payment_reminder, document_request, plan_review,
service_follow_up, reinstatement) use service_channels; retention_offer and add_on_offer use
marketing_channels; internal_task uses channel "internal". "intermediary" means a task for
the broker or employer who owns the relationship. Use the customer's preferred_channel
whenever it is allowed for the action. "email_sms" sends the same short
message by both email and SMS: use it when it is allowed and the matter is urgent (cover at
risk, missed premium, expiry within days).
Prefer fixing cover at risk (missed premium, grace) before any offer.
Score ranges: high 0.6-1.0, medium 0.3-0.7, low 0.0-0.4.
Set needs_review true when the case is unusual or your confidence is low.
{REASON_GUIDE}
""".strip()


def _errors(
    d: LapseDecision, a: RenewalAssessment, signals: dict[str, Any], preferred: str | None
) -> list[str]:
    errs = grounding_errors(d.reasons, signals) + score_band_errors(d.score, d.band, BAND_RANGES)
    errs += [
        r.reason
        for r in validate_intervention(
            a,
            action=d.intervention,
            channel=d.channel,
            discount_pct=d.discount_pct,
        )
    ]
    if d.intervention == Action.ADD_ON_OFFER and not a.add_on_options:
        errs.append("add_on_offer needs at least one eligible add-on")
    offer = d.intervention in (Action.RETENTION_OFFER, Action.ADD_ON_OFFER)
    allowed = a.marketing_channels if offer else a.service_channels
    single = d.channel in (Channel.EMAIL, Channel.SMS)
    if preferred in allowed and single and d.channel != preferred:
        errs.append(f"customer prefers {preferred}; use it (or email_sms if urgent)")
    return errs


async def decide_lapse(
    llm: LLMClient,
    *,
    signals: dict[str, Any],
    assessment: RenewalAssessment,
    preferred_channel: str | None = None,
) -> LapseDecision:
    a = assessment
    return await llm.structured(
        LapseDecision,
        purpose=PURPOSE,
        instructions=INSTRUCTIONS,
        task="Assess lapse risk and choose an intervention.",
        data={
            "signals": signals,
            "state": a.state.value,
            "triggers": [{"type": t.type.value, "detail": t.detail} for t in a.triggers],
            "allowed_actions": [x.value for x in a.allowed_actions],
            "service_channels": [c.value for c in a.service_channels],
            "marketing_channels": [c.value for c in a.marketing_channels],
            "max_discount_pct": a.max_discount_pct,
            "add_on_options": a.add_on_options,
            "preferred_channel": preferred_channel,
        },
        validate=lambda d: _errors(d, a, signals, preferred_channel),
    )
