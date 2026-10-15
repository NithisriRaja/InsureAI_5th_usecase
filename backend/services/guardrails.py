"""Non-negotiable guardrails, enforced in code (not only in prompts).

The agent never binds, issues or renews cover, never prices outside the approved cap, never
declines, never sends without approval and never goes around the broker / employer that owns
the relationship. ``check_recommendation`` runs on every recommendation before it is stored;
a violation raises (the run fails) and is written to the audit log by the caller.
"""

from __future__ import annotations

from typing import Any

from backend import rulebook
from backend.enums import CUSTOMER_CHANNELS, Action
from backend.services.rules.routing import owns_via_intermediary


class GuardrailViolation(Exception):
    code = "guardrail_violation"

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(f"{rule}: {message}")
        self.rule = rule


def assert_agent_may(action: str) -> None:
    """Only actions in the approval matrix may be proposed; forbidden ones never."""
    if action in rulebook.FORBIDDEN_AGENT_ACTIONS:
        raise GuardrailViolation("guardrail.forbidden_action", f"agent may not '{action}'")
    if action not in rulebook.APPROVAL_MATRIX:
        raise GuardrailViolation("guardrail.unknown_action", f"'{action}' not in approval matrix")


def check_recommendation(rec: dict[str, Any]) -> None:
    """Raise if a recommendation draft breaks a guardrail. ``rec`` = column values."""
    action = rec["action"]
    assert_agent_may(action)
    channel = rec.get("channel")
    if channel in CUSTOMER_CHANNELS and owns_via_intermediary(rec.get("channel_owner")):
        raise GuardrailViolation(
            "guardrail.bypass_intermediary",
            f"{rec.get('channel_owner')}-owned relationship cannot be messaged directly",
        )
    offer = rec.get("offer") or {}
    if offer.get("discount_pct"):
        if action != Action.RETENTION_OFFER:
            raise GuardrailViolation("guardrail.pricing", "discount outside a retention offer")
        if offer["discount_pct"] > offer.get("max_discount_pct", 0):
            raise GuardrailViolation("guardrail.pricing", "discount above the approved cap")
    if rec.get("status") not in (None, "pending_approval"):
        raise GuardrailViolation(
            "guardrail.auto_execute", "recommendations must wait for human approval"
        )
