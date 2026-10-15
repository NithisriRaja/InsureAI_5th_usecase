"""Extra-cover choice: which eligible add-on suits this customer best (LLM, grounded)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.agents.shared.decision import (
    REASON_GUIDE,
    Confidence,
    Reason,
    grounding_errors,
)
from backend.services.llm.client import LLMClient

PURPOSE = "add_on_fit"


class AddOnChoice(BaseModel):
    code: str = Field(description="One code from options.")
    confidence: Confidence
    reasons: list[Reason] = Field(min_length=1, max_length=4)
    rationale: str = Field(max_length=400, description="1-2 sentences: why this cover suits.")


INSTRUCTIONS = f"""
You are an insurance adviser's assistant. The customer is eligible for every add-on in options
(the rules already checked age, tenure, cover already held and consent). Pick the one that
suits this customer best given their policy and situation. Never claim it is required or give
a price; the adviser will discuss it with the customer.
{REASON_GUIDE}
""".strip()


def _errors(c: AddOnChoice, codes: list[str], signals: dict[str, Any]) -> list[str]:
    errs = grounding_errors(c.reasons, signals)
    if c.code not in codes:
        errs.append(f"code '{c.code}' is not one of the options {codes}")
    return errs


async def choose_add_on(
    llm: LLMClient, *, signals: dict[str, Any], options: list[dict[str, str]]
) -> AddOnChoice:
    codes = [o["code"] for o in options]
    return await llm.structured(
        AddOnChoice,
        purpose=PURPOSE,
        instructions=INSTRUCTIONS,
        task="Choose the extra cover that suits this customer best.",
        data={"signals": signals, "options": options},
        validate=lambda c: _errors(c, codes, signals),
    )
