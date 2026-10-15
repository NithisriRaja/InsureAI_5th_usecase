"""Deterministic, rule-respecting fake LLM for graph tests (never used by the app)."""

from __future__ import annotations

import json
import re
from typing import Any

from backend.services.llm.client import LLMClient
from backend.services.llm.providers.fake import FakeProvider
from backend.services.llm.ratelimit import RateLimiter
from backend.services.llm.recorder import DbRecorder
from backend.services.llm.retry import RetryPolicy
from backend.services.llm.types import ChatMessage

_DATA = re.compile(r"<data>\n(.*)\n</data>", re.DOTALL)


def payload(messages: list[ChatMessage]) -> dict[str, Any]:
    user = next(m.content for m in messages if m.role == "user")
    return json.loads(_DATA.search(user).group(1))


def _reason(signals: dict[str, Any]) -> list[dict[str, str]]:
    key = next(iter(sorted(signals)))
    return [{"signal": key, "explanation": f"based on {key}"}]


def smart_responder(purpose: str, messages: list[ChatMessage]) -> dict[str, Any]:
    data = payload(messages)
    sig = data.get("signals", {})
    if purpose == "lapse_risk":
        allowed = data["allowed_actions"]
        for pref in (
            "retention_offer",
            "document_request",
            "reinstatement",
            "internal_task",
            "payment_reminder",
            "plan_review",
            "reminder",
        ):
            if pref in allowed:
                action = pref
                break
        else:
            action = allowed[0]
        if action == "internal_task":
            channel, discount = "internal", None
        elif action == "retention_offer":
            channel, discount = data["marketing_channels"][0], min(5, data["max_discount_pct"])
        elif action == "add_on_offer":
            channel, discount = data["marketing_channels"][0], None
        else:
            channel, discount = data["service_channels"][0], None
        return {
            "band": "high",
            "score": 0.8,
            "confidence": "medium",
            "reasons": _reason(sig),
            "intervention": action,
            "channel": channel,
            "discount_pct": discount,
            "rationale": f"Chose {action}.",
            "needs_review": False,
            "review_reason": None,
        }
    if purpose == "add_on_fit":
        code = data["options"][0]["code"]
        return {
            "code": code,
            "confidence": "medium",
            "reasons": _reason(sig),
            "rationale": f"{code} suits this customer.",
        }
    if purpose == "message_draft":
        discount = data.get("discount_pct")
        body = "Hi {first_name}, your policy needs your attention."
        if data["audience"] == "intermediary":
            body = "Please contact your client about their policy."
        if discount:
            body += f" We can offer {discount:g}% off."
        subject = "Your policy" if data["channel"] in ("email", "intermediary") else None
        return {"subject": subject, "body": body}
    raise AssertionError(f"unexpected purpose {purpose}")


def fake_llm(responder=smart_responder) -> tuple[LLMClient, FakeProvider]:
    async def no_sleep(_: float) -> None:
        return None

    provider = FakeProvider(responder)
    client = LLMClient(
        provider,
        mode="prompt",
        limiter=RateLimiter(0, 4),
        retry=RetryPolicy(max_attempts=2, max_total_wait_s=1, base_s=0, cap_s=0, sleep=no_sleep),
        recorder=DbRecorder(),
    )
    return client, provider
