"""Customer message drafts (renewal interventions). Text only; checked by Python afterwards.

The model writes ``{first_name}`` as the only placeholder; Python fills the real name, so
names never enter the prompt.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from backend.services.llm.client import LLMClient
from backend.services.rules.fairness import REDACTED

PURPOSE = "message_draft"
MAX_CHARS = {"email": 1200, "sms": 320, "email_sms": 320}
PLACEHOLDER = "{first_name}"
_PLACEHOLDERS = re.compile(r"\{[^}]*\}|\[[^\]]+\]|<[^>]+>")
_MONEY = re.compile(r"(?:[$€£¤]\s?([\d,]+(?:\.\d+)?))|(?:([\d,]+(?:\.\d+)?)\s?(?:[A-Z]{3})\b)")
_DISCOUNT_WORDS = re.compile(
    r"\b(?:discount(?:ed|s)?|save|saving|savings)\b|%\s*off\b", re.IGNORECASE
)
_MONTHLY = re.compile(r"\b(per month|monthly|/month|a month)\b", re.IGNORECASE)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


class DraftMessage(BaseModel):
    subject: str | None = Field(default=None, max_length=120, description="Email only.")
    body: str = Field(min_length=1)


INSTRUCTIONS = """
You write short, warm, plain-English messages for an insurer.
- audience "customer": a message to an existing customer. Address them as {first_name} (keep
  that exact placeholder; it is filled in later).
- audience "intermediary": a task note to the broker or employer contact who owns the
  relationship, asking them to take the action with their client. Refer to "your client";
  do not address the customer.
Do not use any other placeholders. Do not invent facts, prices, deadlines or discounts that are
not in the data. Copy money amounts exactly as written in the data; never calculate new ones.
Describe premiums only with the premium_period given in the data. If a discount is given,
state exactly that percentage and no other. Never promise cover, acceptance or a price that is
not in the data, and never give financial advice: for reviews and extra cover, invite a
conversation. Sign off exactly as sign_off. SMS must be under 300 characters and have no
subject. Email and intermediary notes need a subject. "email_sms" goes out by both email
and SMS: give it a subject (used for the email) and keep the body under 300 characters so it
also works as a text. No legal promises.
""".strip()


def check_draft(
    d: DraftMessage,
    *,
    channel: str,
    allowed_percents: set[float],
    allowed_amounts: set[float] | None = None,
    premium_change: float | None = None,
    forbid_monthly: bool = True,
    discount_offered: bool | None = None,
    known_names: tuple[str, ...] = (),
) -> list[str]:
    errs: list[str] = []
    body = d.body
    limit = MAX_CHARS.get(channel, 1200)
    if len(body) > limit:
        errs.append(f"body is {len(body)} chars; limit for {channel} is {limit}")
    if channel in ("email", "email_sms", "intermediary") and not (d.subject or "").strip():
        errs.append(f"{channel} message needs a subject")
    if channel == "sms" and d.subject:
        errs.append("sms must not have a subject")
    leftovers = [
        p
        for p in _PLACEHOLDERS.findall(body + " " + (d.subject or ""))
        if p not in (PLACEHOLDER, REDACTED)
    ]
    if leftovers:
        errs.append(f"unresolved placeholders: {leftovers}")
    if REDACTED in body:
        errs.append("draft must not contain redaction markers")
    bad = [
        float(x)
        for x in _PERCENT.findall(body + " " + (d.subject or ""))
        if float(x) not in allowed_percents
    ]
    if bad:
        errs.append(f"percentages {bad} not allowed; allowed: {sorted(allowed_percents)}")
    if allowed_amounts is not None:
        text = body + " " + (d.subject or "")
        found = {float((a or b).replace(",", "")) for a, b in _MONEY.findall(text)}
        wrong = sorted(found - allowed_amounts)
        if wrong:
            errs.append(
                f"money amounts {wrong} are not in the data; copy amounts exactly "
                f"from: {sorted(allowed_amounts)}"
            )
        if discount_offered is None:  # infer: any allowed % other than the premium change
            discount_offered = any(x != premium_change for x in allowed_percents)
        for name in known_names:  # e.g. "Regular Savings Plan" is a name, not an offer
            text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)
            if "saving" in name.casefold():  # savings products talk about "your savings"
                text = re.sub(r"\bsavings?\b", " ", text, flags=re.IGNORECASE)
        if not discount_offered and _DISCOUNT_WORDS.search(text):
            errs.append("no discount is offered; do not mention a discount, saving or % off")
        if forbid_monthly and _MONTHLY.search(text):
            errs.append("premiums are annual; do not mention monthly amounts")
    return errs


def amounts_in(facts: dict[str, Any]) -> set[float]:
    """Money values present in the facts (strings like '1,240.00 USD')."""
    out: set[float] = set()
    for v in facts.values():
        if isinstance(v, str):
            out |= {float((a or b).replace(",", "")) for a, b in _MONEY.findall(v)}
    return out


def render(text: str | None, first_name: str | None) -> str | None:
    if text is None:
        return None
    return text.replace(PLACEHOLDER, (first_name or "there").strip() or "there")


async def draft_message(
    llm: LLMClient,
    *,
    channel: str,
    intervention: str,
    facts: dict[str, Any],
    discount_pct: float | None,
    sign_off: str,
) -> DraftMessage:
    allowed = {float(discount_pct)} if discount_pct else set()
    if isinstance(facts.get("premium_change_pct"), int | float):
        allowed.add(float(facts["premium_change_pct"]))
    audience = "intermediary" if channel == "intermediary" else "customer"
    return await llm.structured(
        DraftMessage,
        purpose=PURPOSE,
        instructions=INSTRUCTIONS,
        task=f"Draft the {channel} message for intervention '{intervention}'.",
        data={
            "audience": audience,
            "channel": channel,
            "intervention": intervention,
            "facts": facts,
            "discount_pct": discount_pct,
            "sign_off": sign_off,
        },
        validate=lambda d: check_draft(
            d,
            channel=channel,
            allowed_percents=allowed,
            allowed_amounts=amounts_in(facts),
            premium_change=facts.get("premium_change_pct"),
            forbid_monthly=facts.get("premium_period") != "monthly",
            discount_offered=bool(discount_pct),
            known_names=tuple(
                str(facts[k]) for k in ("product", "line", "additional_cover") if facts.get(k)
            ),
        ),
    )
