"""Shared graph state and injected dependencies.

Nodes return partial updates. List/dict fields that several nodes contribute to use reducers
so updates accumulate instead of overwrite.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.runnables import RunnableConfig

from backend.db.session import Database
from backend.integrations.base import CRM, Billing, PolicyAdmin
from backend.services.llm.client import LLMClient
from backend.services.rules.facts import RenewalFacts
from backend.services.rules.renewal import RenewalAssessment

Gate = Literal["pass", "skip"]


def merge_dicts(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any]:
    return {**(a or {}), **(b or {})}


class GraphState(TypedDict, total=False):
    # identity
    run_id: str
    use_case: str
    subject_type: str
    subject_id: str
    cycle_key: str
    as_of: date

    # loaded context (never sent to the LLM as-is)
    renewal_facts: RenewalFacts
    assessment: RenewalAssessment
    first_name: str | None
    channel_owner: str | None
    lifecycle_type: str | None
    triggers: list[dict[str, Any]]

    # accumulated evidence
    gate: Gate
    skip_reason: str | None
    signals: dict[str, Any]
    fairness: dict[str, Any]
    rule_results: Annotated[list[dict[str, Any]], operator.add]
    decisions: Annotated[dict[str, Any], merge_dicts]
    forced_review: Annotated[list[str], operator.add]

    # recommendation draft
    action: str
    queue: str
    priority: str
    band: str | None
    confidence: str | None
    explanation: str | None
    offer: dict[str, Any] | None
    cover_suggestion: dict[str, Any] | None
    channel: str | None
    draft_subject: str | None
    draft_message: str | None
    expires_at: datetime | None

    # output
    recommendation_id: str | None


@dataclass
class GraphDeps:
    db: Database
    llm: LLMClient
    crm: CRM
    policy_admin: PolicyAdmin
    billing: Billing
    # Optional override of the expiry notice window (default: rulebook per lifecycle type).
    renewal_window_days: int | None = None


def deps(config: RunnableConfig) -> GraphDeps:
    return config["configurable"]["deps"]
