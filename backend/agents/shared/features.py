"""LLM-safe feature payloads built from an explicit allow-list.

Nothing reaches a decision prompt unless it is listed here. No names, no contact details, no
DOB (age band only), no city/postcode, no protected attributes, no intermediary names. Each
prompt gets only the slice it needs.
"""

from __future__ import annotations

from typing import Any

from backend.config import get_settings
from backend.services.rules.facts import RenewalFacts


def major(minor: int | None) -> float | None:
    """LLM sees whole currency units; the DB stores minor units (cents)."""
    return None if minor is None else round(minor / 100, 2)


def age_band(age: int | None) -> str | None:
    if age is None:
        return None
    if age < 18:
        return "under_18"
    for lo, hi in ((18, 24), (25, 34), (35, 44), (45, 54), (55, 64), (65, 74)):
        if lo <= age <= hi:
            return f"{lo}-{hi}"
    return "75+"


def renewal_signals(f: RenewalFacts, base: dict[str, Any]) -> dict[str, Any]:
    """``base`` = rules.renewal.compute_signals output; add a couple of safe extras."""
    out = {
        **base,
        "customer_age_band": age_band(f.customer_age),
        "currency": get_settings().currency,
        "sum_insured": major(f.sum_insured),
    }
    if f.payment_frequency != "single":
        out["premium"] = major(f.premium)
    if f.lifecycle_type in ("expiry_renewal", "group_scheme_renewal"):
        out["prev_premium"] = major(f.prev_premium)
    return out
