"""Recommendation agent: finds extra cover the customer is eligible for and that suits them.

The renewal rules list the add-ons a customer may be offered (not already held, age and tenure
fit, marketing consent). For every customer with at least one eligible add-on, this agent picks
the best-suited one: the only option directly, or the best of several with a grounded LLM
judgement. The pick is stored as ``cover_suggestion`` so the adviser always sees it.

It only becomes the customer message when the retention agent chose an extra-cover
conversation (``add_on_offer``) as the next step; otherwise the message deals with the more
urgent matter (payment, renewal, documents) and the suggestion waits for the adviser.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from backend.agents.recommendation.decision import choose_add_on
from backend.agents.shared.node import node
from backend.agents.state import GraphState, deps
from backend.enums import Action
from backend.utils.audit import audit


class NoEligibleAddOn(ValueError):
    code = "no_eligible_add_on"


@node("recommendation")
async def recommendation(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    f, a = state["renewal_facts"], state["assessment"]
    eligible = [c for c in f.add_on_candidates if c.code in a.add_on_options]
    offered = state["action"] == Action.ADD_ON_OFFER
    if offered and not eligible:
        raise NoEligibleAddOn(f"no eligible add-on for policy {state['subject_id']}")

    out: dict[str, Any] = {}
    pick = None
    if len(eligible) == 1:
        cand = eligible[0]
        pick = {
            "code": cand.code,
            "name": cand.name,
            "rationale": f"{cand.name} is the extra cover this customer is eligible for.",
        }
    elif eligible:
        choice = await choose_add_on(
            d.llm,
            signals=state["signals"],
            options=[
                {"code": c.code, "name": c.name, "description": c.description} for c in eligible
            ],
        )
        cand = next(c for c in eligible if c.code == choice.code)
        pick = {"code": cand.code, "name": cand.name, "rationale": choice.rationale}
        out["decisions"] = {"add_on_fit": choice.model_dump(mode="json")}
    if pick:
        out["cover_suggestion"] = pick
        if offered:
            out["offer"] = {"type": "add_on", **pick}
    await audit(
        d.db,
        "node.recommendation",
        {
            "offered": offered,
            "code": pick["code"] if pick else None,
            "eligible": [c.code for c in eligible],
        },
        subject_type="policy",
        subject_id=state["subject_id"],
    )
    return out
