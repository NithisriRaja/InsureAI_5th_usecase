"""Renewal agent: watches every policy's lifecycle (expiry, payments, pending documents).

Loads the policy, customer, product and payments through the integration adapters and runs
the lifecycle rules: which triggers fired, whether the policy is in scope, which next steps
are allowed. No LLM here.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from backend.agents.shared import features
from backend.agents.shared.node import SubjectNotFound, node
from backend.agents.state import GraphState, deps
from backend.services.rules import renewal as renewal_rules
from backend.services.rules.facts import renewal_facts
from backend.services.rules.types import dump
from backend.utils.audit import audit


@node("renewal")
async def renewal(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    policy = await d.policy_admin.get_policy(state["subject_id"])
    if policy is None:
        raise SubjectNotFound(f"policy {state['subject_id']} not found")
    customer = await d.crm.get_customer(policy.customer_id)
    product = await d.policy_admin.get_product(policy.product_code)
    if customer is None or product is None:
        raise SubjectNotFound(f"policy {policy.id} has no customer/product")
    payments = list(await d.billing.payments_for(policy.id))
    add_ons = [p for c in product.add_ons or [] if (p := await d.policy_admin.get_product(c))]

    facts = renewal_facts(policy, customer, product, payments, state["as_of"], add_ons)
    a = renewal_rules.assess(facts, d.renewal_window_days)
    gate = "skip" if a.state == renewal_rules.RenewalState.SKIP else "pass"
    await audit(
        d.db,
        "node.renewal",
        {
            "lifecycle_type": a.lifecycle_type,
            "state": a.state.value,
            "skip_reason": a.skip_reason,
            "triggers": [t.type.value for t in a.triggers],
            "allowed_actions": [x.value for x in a.allowed_actions],
            "max_discount_pct": a.max_discount_pct,
            "add_on_options": a.add_on_options,
            "channel_owner": facts.channel_owner,
        },
        subject_type="policy",
        subject_id=policy.id,
    )
    return {
        "renewal_facts": facts,
        "assessment": a,
        "first_name": customer.first_name,
        "channel_owner": facts.channel_owner,
        "lifecycle_type": a.lifecycle_type,
        "triggers": [t.model_dump(mode="json") for t in a.triggers],
        "gate": gate,
        "skip_reason": a.skip_reason,
        "signals": features.renewal_signals(facts, a.signals),
        "rule_results": dump(a.results),
        "expires_at": a.expires_at,
        "fairness": {"passed": True, "redactions": 0, "categories": [], "violations": []},
    }


def route_after_renewal(state: GraphState) -> str:
    return "workflow" if state["gate"] == "skip" else "retention"
