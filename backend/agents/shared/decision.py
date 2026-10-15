"""Shared decision output pieces: bands, confidence, grounded reasons."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Reason(BaseModel):
    signal: str = Field(description="Exact key of the signal this reason is based on.")
    explanation: str = Field(max_length=300)


# How every free-text field should read: a sharp colleague, not a report generator.
STYLE_GUIDE = (
    "Voice for all free text: crisp, natural and human, like a sharp colleague briefing a "
    "busy approver. Lead with the point. Short sentences, active voice, concrete numbers. "
    "A touch of personality is welcome; no filler ('indicating', 'suggests that', 'it is "
    "important to note'), no hedging, no jargon. Each reason: one line, at most ~18 words."
)

REASON_GUIDE = (
    "Give 1-5 reasons. Each reason MUST name in `signal` the exact key of one signal from the "
    "data that supports it. Do not invent signals or facts that are not in the data. " + STYLE_GUIDE
)


def grounding_errors(reasons: Iterable[Reason], signals: dict[str, Any]) -> list[str]:
    reasons = list(reasons)
    if not reasons:
        return ["reasons: at least one reason is required"]
    return [
        f"reasons[{i}].signal: '{r.signal}' is not one of the provided signals {sorted(signals)}"
        for i, r in enumerate(reasons)
        if r.signal not in signals
    ]


def score_band_errors(score: float, band: str, ranges: dict[str, tuple[float, float]]) -> list[str]:
    lo, hi = ranges[band]
    if not lo <= score <= hi:
        return [f"score {score} is inconsistent with band '{band}' (expected {lo}-{hi})"]
    return []
