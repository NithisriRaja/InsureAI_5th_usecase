"""UC5 lifecycle rules: which events fired, cover state, allowed interventions, offer caps.

The product's **lifecycle type** decides which triggers may fire (``rulebook.LIFECYCLES``):

- expiry lifecycles (fixed term, group schemes): upcoming expiry / scheme anniversary inside
  the notice window, grace after expiry, reinstatement after that.
- premium lifecycles (life, savings): missed premium (grace, then lapse), lapse-risk signals,
  scheduled reviews, milestones. They never get an expiry trigger, whatever ``end_date`` is.

State is derived from dates and payments, not the stored status, except for the terminal
statuses ``cancelled`` / ``renewed`` (the stored status can lag behind the calendar).
"""

from __future__ import annotations

import datetime as _dt
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend import rulebook
from backend.enums import (
    EXPIRY_LIFECYCLES,
    Action,
    Channel,
    LifecycleType,
    PolicyStatus,
    Trigger,
)
from backend.services.rules.consent import renewal_channels
from backend.services.rules.facts import RenewalFacts
from backend.services.rules.types import RuleResult, Severity


class RenewalState(StrEnum):
    DUE = "due"  # an event needs action, cover not at risk yet
    IN_GRACE = "in_grace"  # expired / premium missed, still inside the grace period
    LAPSED = "lapsed"  # past grace, reinstatement window open
    SKIP = "skip"


class TriggerHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Trigger
    date: _dt.date | None = None
    detail: str


class RenewalAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: RenewalState
    skip_reason: str | None
    lifecycle_type: str
    triggers: list[TriggerHit]
    next_event_type: str | None
    next_event_date: date | None
    signals: dict[str, Any]
    allowed_actions: list[Action]
    service_channels: list[Channel]
    marketing_channels: list[Channel]
    max_discount_pct: int
    add_on_options: list[str]
    results: list[RuleResult]
    expires_at: datetime | None

    @property
    def cycle_key_suffix(self) -> str:
        return f"{self.next_event_type or 'none'}:{self.next_event_date or 'open'}"


def is_expiry(f: RenewalFacts) -> bool:
    return f.lifecycle_type in EXPIRY_LIFECYCLES


def window_days(f: RenewalFacts, override: int | None = None) -> int:
    """Expiry notice window. The optional override (scan / settings) applies to one-year
    expiry renewals only; group schemes keep their longer rulebook notice."""
    lc = rulebook.LIFECYCLES[f.lifecycle_type]
    if not is_expiry(f):
        return lc.get("review_notice_days", 0)
    if override and f.lifecycle_type == LifecycleType.EXPIRY_RENEWAL:
        return override
    return max(lc["notice_days"])


def premium_change_pct(f: RenewalFacts) -> float:
    if not f.prev_premium or not is_expiry(f):
        return 0.0
    return round((f.premium - f.prev_premium) / f.prev_premium * 100, 1)


def compute_signals(f: RenewalFacts, triggers: list[TriggerHit]) -> dict[str, Any]:
    """Measurable lifecycle signals; LLM reasons must cite these keys."""
    s: dict[str, Any] = {
        "line": f.line,
        "lifecycle_type": f.lifecycle_type,
        "channel_owner": f.channel_owner,
        "payment_frequency": f.payment_frequency,
        "triggers": [t.type.value for t in triggers],
        "grace_days": f.product_grace_days,
        "overdue_payments": f.overdue_payments,
        "failed_payments": f.failed_payments,
        "docs_outstanding_count": len(f.docs_outstanding),
        "tenure_years": f.tenure_years,
        "claims_count_3y": f.claims_count_3y,
        "service_complaints_12m": f.service_complaints_12m,
    }
    if is_expiry(f):
        s["days_to_expiry"] = (f.end_date - f.as_of).days
        s["premium_change_pct"] = premium_change_pct(f)
        s["auto_renew"] = f.auto_renew
    if f.oldest_overdue_due:
        s["days_premium_overdue"] = (f.as_of - f.oldest_overdue_due).days
    if f.review_due_date and not is_expiry(f):
        s["days_to_review"] = (f.review_due_date - f.as_of).days
    if f.milestone_date and f.lifecycle_type == LifecycleType.MILESTONE:
        s["days_to_milestone"] = (f.milestone_date - f.as_of).days
    return s


def _lapse_signals(f: RenewalFacts) -> list[str]:
    out = []
    if f.failed_payments:
        out.append(f"{f.failed_payments} failed payment(s)")
    if f.service_complaints_12m:
        out.append(f"{f.service_complaints_12m} complaint(s) in 12 months")
    if is_expiry(f) and premium_change_pct(f) >= rulebook.LAPSE_SIGNAL_PRICE_SHOCK_PCT:
        out.append(f"renewal premium up {premium_change_pct(f)}%")
    return out


def _expiry_events(
    f: RenewalFacts, window: int
) -> tuple[RenewalState, str | None, list[TriggerHit]]:
    lc = rulebook.LIFECYCLES[f.lifecycle_type]
    days = (f.end_date - f.as_of).days
    if days > window:
        return RenewalState.SKIP, "out_of_window", []
    kind = (
        Trigger.SCHEME_ANNIVERSARY
        if f.lifecycle_type == LifecycleType.GROUP_SCHEME_RENEWAL
        else Trigger.UPCOMING_EXPIRY
    )
    if days >= 0:
        state = RenewalState.DUE
        notice = min((n for n in lc["notice_days"] if n >= days), default=window)
        detail = f"Ends in {days} day(s) ({notice}-day notice point)."
    elif -days <= f.product_grace_days:
        state, detail = RenewalState.IN_GRACE, f"Ended {-days} day(s) ago; in grace."
    elif -days <= lc["reinstatement_lookback_days"]:
        state, detail = RenewalState.LAPSED, f"Ended {-days} day(s) ago; lapsed."
    else:
        return RenewalState.SKIP, "lapsed_beyond_lookback", []
    hits = [TriggerHit(type=kind, date=f.end_date, detail=detail)]
    if f.docs_outstanding and days <= lc["missing_document_before_days"]:
        hits.append(
            TriggerHit(
                type=Trigger.MISSING_DOCUMENT,
                detail=f"Outstanding: {', '.join(f.docs_outstanding)}.",
            )
        )
    if f.overdue_payments:
        hits.append(
            TriggerHit(
                type=Trigger.PAYMENT_OVERDUE,
                date=f.oldest_overdue_due,
                detail=f"{f.overdue_payments} overdue instalment(s).",
            )
        )
    signals = _lapse_signals(f)
    if signals:
        hits.append(TriggerHit(type=Trigger.LAPSE_RISK_SIGNAL, detail="; ".join(signals) + "."))
    return state, None, hits


def _premium_events(f: RenewalFacts) -> tuple[RenewalState, str | None, list[TriggerHit]]:
    lc = rulebook.LIFECYCLES[f.lifecycle_type]
    allowed = lc["triggers"]
    state = RenewalState.DUE
    hits: list[TriggerHit] = []
    if Trigger.PREMIUM_MISSED in allowed and f.oldest_overdue_due:
        overdue_days = (f.as_of - f.oldest_overdue_due).days
        if overdue_days > lc["reinstatement_lookback_days"]:
            return RenewalState.SKIP, "lapsed_beyond_lookback", []
        if overdue_days > f.product_grace_days:
            state, where = RenewalState.LAPSED, "past grace; lapsed"
        else:
            state, where = RenewalState.IN_GRACE, "in grace"
        hits.append(
            TriggerHit(
                type=Trigger.PREMIUM_MISSED,
                date=f.oldest_overdue_due,
                detail=f"Premium {overdue_days} day(s) overdue ({where}).",
            )
        )
    if Trigger.LAPSE_RISK_SIGNAL in allowed:
        signals = _lapse_signals(f)
        if signals:
            hits.append(TriggerHit(type=Trigger.LAPSE_RISK_SIGNAL, detail="; ".join(signals) + "."))
    if Trigger.MILESTONE in allowed and f.milestone_date:
        days = (f.milestone_date - f.as_of).days
        if 0 <= days <= lc["milestone_notice_days"]:
            hits.append(
                TriggerHit(
                    type=Trigger.MILESTONE,
                    date=f.milestone_date,
                    detail=f"{f.milestone_label or 'Plan milestone'} in {days} day(s).",
                )
            )
    if Trigger.SCHEDULED_REVIEW in allowed and f.review_due_date:
        days = (f.review_due_date - f.as_of).days
        if days <= lc["review_notice_days"]:
            when = f"due in {days} day(s)" if days >= 0 else f"overdue by {-days} day(s)"
            hits.append(
                TriggerHit(
                    type=Trigger.SCHEDULED_REVIEW,
                    date=f.review_due_date,
                    detail=f"Plan review {when}.",
                )
            )
    if Trigger.MISSING_DOCUMENT in allowed and f.docs_outstanding:
        hits.append(
            TriggerHit(
                type=Trigger.MISSING_DOCUMENT,
                detail=f"Outstanding: {', '.join(f.docs_outstanding)}.",
            )
        )
    if not hits:
        return RenewalState.SKIP, "no_trigger", []
    return state, None, hits


# Order in which a fired trigger becomes the "next event" (and the run's cycle key).
_EVENT_PRIORITY = (
    Trigger.UPCOMING_EXPIRY,
    Trigger.SCHEME_ANNIVERSARY,
    Trigger.PREMIUM_MISSED,
    Trigger.MILESTONE,
    Trigger.SCHEDULED_REVIEW,
    Trigger.PAYMENT_OVERDUE,
    Trigger.LAPSE_RISK_SIGNAL,
    Trigger.MISSING_DOCUMENT,
)


def lifecycle_state(
    f: RenewalFacts, window_override: int | None = None
) -> tuple[RenewalState, str | None, list[TriggerHit]]:
    if f.policy_status == PolicyStatus.CANCELLED:
        return RenewalState.SKIP, "cancelled", []
    if f.policy_status == PolicyStatus.RENEWED:
        return RenewalState.SKIP, "already_renewed", []
    if is_expiry(f):
        return _expiry_events(f, window_days(f, window_override))
    return _premium_events(f)


def offer_eligible(f: RenewalFacts, marketing_channels: list[Channel]) -> RuleResult:
    reasons = []
    if not is_expiry(f):
        reasons.append("renewal discounts apply to fixed-term products only")
    if not marketing_channels:
        reasons.append("no marketing consent/channel")
    if f.tenure_years < rulebook.OFFER_MIN_TENURE_YEARS:
        reasons.append(f"tenure < {rulebook.OFFER_MIN_TENURE_YEARS} years")
    if f.claims_count_3y > rulebook.OFFER_MAX_CLAIMS_3Y:
        reasons.append(f"more than {rulebook.OFFER_MAX_CLAIMS_3Y} claim(s) in 3 years")
    if f.overdue_payments or f.failed_payments:
        reasons.append("outstanding payments")
    if f.product_max_discount_pct <= 0:
        reasons.append("product allows no discount")
    if reasons:
        return RuleResult.fail(
            "renewal.offer_eligibility", Severity.INFO, "Offer not allowed: " + "; ".join(reasons)
        )
    return RuleResult.ok(
        "renewal.offer_eligibility",
        f"Retention offer allowed up to {f.product_max_discount_pct}%.",
        max_discount_pct=f.product_max_discount_pct,
    )


def add_on_options(
    f: RenewalFacts, state: RenewalState, marketing_channels: list[Channel]
) -> tuple[list[str], RuleResult | None]:
    """Suitability gate for extra cover. The suggestion itself is approved by an adviser."""
    if not f.add_on_candidates:
        return [], None
    reasons = []
    if state != RenewalState.DUE:
        reasons.append("cover is at risk; fix that first")
    if not marketing_channels:
        reasons.append("no marketing consent/channel")
    if f.tenure_years < rulebook.ADD_ON_MIN_TENURE_YEARS:
        reasons.append(f"tenure < {rulebook.ADD_ON_MIN_TENURE_YEARS} year")
    if f.overdue_payments or f.failed_payments:
        reasons.append("outstanding payments")
    fits = [
        c.code
        for c in f.add_on_candidates
        if f.customer_age is not None and c.min_age <= f.customer_age <= c.max_age
    ]
    if not fits:
        reasons.append("customer outside every add-on's age band")
    if reasons:
        return [], RuleResult.fail(
            "suitability.add_on", Severity.INFO, "Add-on not suitable now: " + "; ".join(reasons)
        )
    return fits, RuleResult.ok(
        "suitability.add_on", f"Add-on cover may be suggested: {', '.join(fits)}.", codes=fits
    )


def _expires_at(f: RenewalFacts, state: RenewalState, event_date: date | None) -> datetime:
    if state == RenewalState.LAPSED:
        day = f.as_of + timedelta(days=rulebook.LAPSED_REC_TTL_DAYS)
    elif is_expiry(f):
        day = f.end_date + timedelta(days=f.product_grace_days)
    elif state == RenewalState.IN_GRACE and f.oldest_overdue_due:
        day = f.oldest_overdue_due + timedelta(days=f.product_grace_days)
    else:
        day = max(f.as_of, event_date or f.as_of) + timedelta(days=rulebook.EVENT_REC_TTL_DAYS)
    return datetime.combine(day, time(23, 59, 59), tzinfo=UTC)


def assess(f: RenewalFacts, window_override: int | None = None) -> RenewalAssessment:
    state, skip_reason, hits = lifecycle_state(f, window_override)
    signals = compute_signals(f, hits)
    service = renewal_channels(f, "service")
    marketing = renewal_channels(f, "marketing")
    results: list[RuleResult] = []
    first = next((h for t in _EVENT_PRIORITY for h in hits if h.type == t), None)

    def build(**kw: Any) -> RenewalAssessment:
        return RenewalAssessment(
            lifecycle_type=f.lifecycle_type,
            triggers=hits,
            next_event_type=first.type.value if first else None,
            next_event_date=first.date if first else None,
            signals=signals,
            service_channels=service,
            marketing_channels=marketing,
            results=results,
            **kw,
        )

    if state == RenewalState.SKIP:
        results.append(
            RuleResult.fail("renewal.lifecycle", Severity.INFO, f"Skipped: {skip_reason}.")
        )
        return build(
            state=state,
            skip_reason=skip_reason,
            allowed_actions=[],
            max_discount_pct=0,
            add_on_options=[],
            expires_at=None,
        )

    results.append(
        RuleResult.ok(
            "renewal.lifecycle",
            f"{f.lifecycle_type}: {state.value}; triggers: "
            + ", ".join(h.type.value for h in hits)
            + ".",
            state=state,
            triggers=[h.type.value for h in hits],
        )
    )
    allowed: list[Action] = []
    max_discount = 0
    add_ons: list[str] = []

    if not service:
        results.append(
            RuleResult.fail(
                "consent.service_channel",
                Severity.WARN,
                "No consented contact channel: internal task only, no customer message.",
            )
        )
        allowed = [Action.INTERNAL_TASK]
    elif state == RenewalState.LAPSED:
        allowed = [Action.REINSTATEMENT]
    else:
        for h in hits:
            action = rulebook.TRIGGER_ACTIONS[h.type]
            if action not in allowed:
                allowed.append(action)
        if f.failed_payments and Action.PAYMENT_REMINDER not in allowed:
            allowed.append(Action.PAYMENT_REMINDER)
        if is_expiry(f):
            offer = offer_eligible(f, marketing)
            results.append(offer)
            if offer.passed:
                allowed.append(Action.RETENTION_OFFER)
                max_discount = f.product_max_discount_pct
        add_ons, suit = add_on_options(f, state, marketing)
        if suit is not None:
            results.append(suit)
        if add_ons:
            allowed.append(Action.ADD_ON_OFFER)

    if service == [Channel.INTERMEDIARY]:
        results.append(
            RuleResult.ok(
                "routing.intermediary",
                f"{f.channel_owner.capitalize()} owns the relationship: task to the "
                f"{f.channel_owner}, no direct customer message.",
            )
        )

    return build(
        state=state,
        skip_reason=None,
        allowed_actions=allowed,
        max_discount_pct=max_discount,
        add_on_options=add_ons,
        expires_at=_expires_at(f, state, first.date if first else None),
    )


def validate_intervention(
    a: RenewalAssessment,
    *,
    action: str,
    channel: str | None,
    discount_pct: float | None,
    add_on_code: str | None = None,
) -> list[RuleResult]:
    """Re-check a (possibly human-edited) intervention. Empty list = valid."""
    errs: list[RuleResult] = []
    if action not in a.allowed_actions:
        errs.append(
            RuleResult.fail(
                "renewal.action_not_allowed",
                Severity.BLOCK,
                f"Action '{action}' not allowed; allowed: {[x.value for x in a.allowed_actions]}.",
            )
        )
    if action == Action.RETENTION_OFFER:
        if discount_pct is None or discount_pct <= 0:
            errs.append(
                RuleResult.fail(
                    "renewal.offer_discount_missing", Severity.BLOCK, "Offer needs a discount > 0."
                )
            )
        elif discount_pct > a.max_discount_pct:
            errs.append(
                RuleResult.fail(
                    "renewal.discount_cap",
                    Severity.BLOCK,
                    f"Discount {discount_pct}% exceeds cap {a.max_discount_pct}%.",
                )
            )
        allowed_channels = a.marketing_channels
    elif discount_pct:
        errs.append(
            RuleResult.fail(
                "renewal.discount_without_offer",
                Severity.BLOCK,
                "Discount only allowed on retention offers.",
            )
        )
        allowed_channels = a.service_channels
    elif action == Action.ADD_ON_OFFER:
        if add_on_code is not None and add_on_code not in a.add_on_options:
            errs.append(
                RuleResult.fail(
                    "suitability.add_on",
                    Severity.BLOCK,
                    f"Add-on '{add_on_code}' not suitable; allowed: {a.add_on_options}.",
                )
            )
        allowed_channels = a.marketing_channels
    else:
        allowed_channels = a.service_channels

    if action == Action.INTERNAL_TASK:
        if channel not in (None, Channel.INTERNAL):
            errs.append(
                RuleResult.fail(
                    "consent.channel", Severity.BLOCK, "Internal task cannot contact the customer."
                )
            )
    elif channel not in allowed_channels:
        allowed = [c.value for c in allowed_channels]
        errs.append(
            RuleResult.fail(
                "consent.channel",
                Severity.BLOCK,
                f"Channel '{channel}' not allowed; allowed: {allowed}.",
            )
        )
    return errs
