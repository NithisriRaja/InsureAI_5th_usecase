"""UC5 lifecycle monitor: assess a policy against the rulebook from current data.

Shared by the renewal scan, single runs, the worklist, approvals (staleness) and the
dashboard so they all agree on what is due and on the cycle key of each lifecycle event.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from backend.agents.graph import cycle_key_for
from backend.config import get_settings
from backend.db.models import Policy, Product
from backend.db.repositories import policies as policies_repo
from backend.db.store import DbSession
from backend.enums import PolicyStatus
from backend.services.rules import renewal as renewal_rules
from backend.services.rules.facts import RenewalFacts, renewal_facts
from backend.utils.clock import today

TERMINAL = (PolicyStatus.CANCELLED, PolicyStatus.RENEWED)


async def facts_for(
    s: DbSession, policy: Policy, as_of: date | None = None
) -> RenewalFacts | None:
    customer = await policies_repo.get_customer(s, policy.customer_id)
    product = await policies_repo.get_product(s, policy.product_code)
    if customer is None or product is None:
        return None
    payments = list(await policies_repo.payments_for(s, policy.id))
    add_ons: list[Product] = []
    if product.add_ons:
        add_ons = [p for code in product.add_ons if (p := await s.get(Product, code))]
    return renewal_facts(policy, customer, product, payments, as_of or today(), add_ons)


async def assess_policy(
    s: DbSession, policy: Policy, *, window_days: int | None = None
) -> renewal_rules.RenewalAssessment | None:
    facts = await facts_for(s, policy)
    if facts is None:
        return None
    return renewal_rules.assess(facts, window_days or get_settings().renewal_window_days)


def cycle_key(policy_id: str, a: renewal_rules.RenewalAssessment) -> str:
    return cycle_key_for(policy_id, a.cycle_key_suffix)


def record_next_event(policy: Policy, a: renewal_rules.RenewalAssessment) -> None:
    """Persist the monitor's view on the policy row (worklist sorting / display)."""
    policy.next_event_type = a.next_event_type
    policy.next_event_date = a.next_event_date


async def monitored_policies(s: DbSession) -> list[Policy]:
    return sorted(s.where(Policy, lambda p: p.status not in TERMINAL), key=lambda p: p.id)


async def assess_many(
    s: DbSession, policies: Iterable[Policy], *, window_days: int | None = None
) -> dict[str, renewal_rules.RenewalAssessment]:
    out = {}
    for p in policies:
        a = await assess_policy(s, p, window_days=window_days)
        if a is not None:
            out[p.id] = a
    return out
