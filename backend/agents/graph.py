"""Use case 5 agent graph: policy renewals, retention and personalised offers.

START -> renewal -(nothing due)-> workflow
         renewal -> retention -> recommendation -> personalisation -> workflow
workflow -> END

- renewal          tracks expiries, payment status and pending documents (rules, no LLM)
- retention        rates the risk of not renewing and picks the next step (LLM, rule-bounded)
- recommendation   turns an extra-cover choice into a concrete, eligible offer
- personalisation  drafts the message for that step from the facts it needs (LLM)
- workflow         stores the follow-up for human approval; delivers it once approved
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.agents.personalisation.agent import personalisation
from backend.agents.recommendation.agent import recommendation
from backend.agents.renewal.agent import renewal, route_after_renewal
from backend.agents.retention.agent import retention
from backend.agents.state import GraphDeps, GraphState
from backend.agents.workflow.agent import workflow
from backend.enums import SubjectType, UseCase
from backend.utils.clock import today
from backend.utils.context import run_context


def build_graph() -> Any:
    g = StateGraph(GraphState)
    for name, fn in [
        ("renewal", renewal),
        ("retention", retention),
        ("recommendation", recommendation),
        ("personalisation", personalisation),
        ("workflow", workflow),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "renewal")
    g.add_conditional_edges("renewal", route_after_renewal, ["retention", "workflow"])
    g.add_edge("retention", "recommendation")
    g.add_edge("recommendation", "personalisation")
    g.add_edge("personalisation", "workflow")
    g.add_edge("workflow", END)
    return g.compile()


@lru_cache
def get_graph() -> Any:
    return build_graph()


def cycle_key_for(subject_id: str, event: Any = None) -> str:
    """One cycle per lifecycle event (``RenewalAssessment.cycle_key_suffix``, e.g.
    ``upcoming_expiry:2026-11-01``)."""
    return f"{subject_id}:{event}" if event else subject_id


async def run_graph(
    *,
    run_id: str,
    use_case: str,
    subject_type: str,
    subject_id: str,
    cycle_key: str,
    deps: GraphDeps,
) -> GraphState:
    if use_case != UseCase.RENEWAL or subject_type != SubjectType.POLICY:
        raise ValueError(f"unsupported run: use_case={use_case!r} subject_type={subject_type!r}")
    state: GraphState = {
        "run_id": run_id,
        "use_case": use_case,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "cycle_key": cycle_key,
        "as_of": today(),
        "rule_results": [],
        "decisions": {},
        "forced_review": [],
    }
    with run_context(run_id):
        return await get_graph().ainvoke(state, config={"configurable": {"deps": deps}})
