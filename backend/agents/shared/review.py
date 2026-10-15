"""Combine the LLM's own review flag with deterministic triggers. Python always wins."""

from __future__ import annotations

from collections.abc import Iterable


def needs_review(
    *,
    llm_flag: bool,
    llm_reason: str | None,
    confidences: Iterable[str | None],
    forced: Iterable[str] = (),
) -> tuple[bool, list[str]]:
    reasons = [r for r in forced if r]
    if any(c == "low" for c in confidences):
        reasons.append("LLM confidence is low")
    if llm_flag:
        reasons.append(f"LLM flagged: {llm_reason or 'no reason given'}")
    return bool(reasons), reasons
