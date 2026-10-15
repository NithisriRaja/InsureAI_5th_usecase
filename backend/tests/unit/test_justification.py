from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from backend.services import justification


def _rec(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "use_case": "renewal",
        "action": "payment_reminder",
        "queue": "retention",
        "priority": "high",
        "channel": "email",
        "channel_owner": "direct",
        "confidence": "high",
        "rule_results": [],
        "decisions": {},
        "signals": {},
        "offer": None,
        "fairness": {"passed": True, "redactions": 0, "categories": [], "violations": []},
        "review_reasons": [],
        "triggers": [],
        "draft_message": None,
        "rulebook_version": "test",
    }
    return SimpleNamespace(**(base | kw))


def _r(id: str, passed: bool, severity: str = "info", reason: str = "r") -> dict[str, Any]:
    return {"id": id, "passed": passed, "severity": severity, "reason": reason, "data": {}}


def test_payment_reminder_explains_rule_and_ai_path() -> None:
    rec = _rec(
        rule_results=[_r("renewal.lifecycle", True, reason="Premium overdue: in grace.")],
        decisions={
            "lapse_risk": {
                "band": "high",
                "confidence": "high",
                "score": 0.8,
                "reasons": [{"signal": "overdue_payments", "explanation": "two missed premiums"}],
            }
        },
        signals={"overdue_payments": 2},
        triggers=[{"type": "premium_missed", "detail": "Premium 20 day(s) overdue"}],
        draft_message="Hi Sam",
    )
    j = justification.build(rec, [])
    assert "send a payment reminder" in j["summary"]
    assert "high" in j["summary"]
    keys = [s["key"] for s in j["steps"]]
    assert keys[:3] == ["lifecycle", "allowed", "lapse"]
    assert {"choice", "message", "routing", "fairness"} <= set(keys)
    lapse = next(s for s in j["steps"] if s["key"] == "lapse")
    assert "overdue payments = 2: two missed premiums" in lapse["details"]
    assert j["headline"].startswith("Money's late")
    assert "premium missed" in j["why"]
    assert j["cited_facts"][0]["judgement"] == "Renewal risk"
    assert j["ai_used"]


def test_intermediary_and_low_confidence_become_approver_checks() -> None:
    rec = _rec(
        action="reminder",
        channel="intermediary",
        channel_owner="broker",
        confidence="low",
        decisions={"lapse_risk": {"band": "low", "confidence": "low", "reasons": []}},
        draft_message="Please contact your client.",
    )
    j = justification.build(rec, [])
    kinds = {c["kind"] for c in j["approver_items"]}
    assert {"confidence", "channel", "message"} <= kinds
    routing = next(s for s in j["steps"] if s["key"] == "routing")
    assert any("broker" in d for d in routing["details"])


def test_renewal_uses_allowed_actions_from_run_audit() -> None:
    rec = _rec(
        action="retention_offer",
        queue="retention",
        channel="email",
        confidence="medium",
        offer={"type": "discount", "discount_pct": 6, "max_discount_pct": 12},
        decisions={"lapse_risk": {"band": "medium", "confidence": "medium", "reasons": []}},
        triggers=[{"type": "upcoming_expiry", "detail": "Ends in 20 day(s)"}],
        draft_message="Hello",
    )
    event = SimpleNamespace(
        event_type="node.renewal",
        payload={"state": "due", "allowed_actions": ["reminder", "retention_offer"]},
    )
    j = justification.build(rec, [event])
    allowed = next(s for s in j["steps"] if s["key"] == "allowed")
    assert "make a retention offer" in allowed["details"][0]
    choice = next(s for s in j["steps"] if s["key"] == "choice")
    assert any("within the 12% cap" in d for d in choice["details"])
    assert any("draft" in c for c in j["approver_checks"])
