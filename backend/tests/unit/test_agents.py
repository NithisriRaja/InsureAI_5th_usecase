from __future__ import annotations

import re

import pytest

from backend.agents.graph import cycle_key_for, run_graph
from backend.agents.state import GraphDeps
from backend.db.models import AuditEvent, Customer, LLMCall, Policy, Recommendation, Run
from backend.integrations.mocks import MockBilling, MockCRM, MockPolicyAdmin
from backend.services import lifecycle
from backend.services.llm.types import LLMUnavailable, ProviderError
from backend.services.rules.fairness import scan_payload
from backend.tests.fixtures.fake_llm import fake_llm, payload, smart_responder
from backend.utils.ids import new_id


async def run_subject(db, llm, use_case: str, subject_id: str):
    subject_type = "policy"
    cycle = cycle_key_for(subject_id)
    async with db.session() as s:
        policy = await s.get(Policy, subject_id)
        if policy is not None:
            cycle = lifecycle.cycle_key(subject_id, await lifecycle.assess_policy(s, policy))
    run_id = new_id("run")
    async with db.session() as s:
        s.add(
            Run(
                id=run_id,
                use_case=use_case,
                subject_type=subject_type,
                subject_id=subject_id,
                cycle_key=cycle,
                status="running",
            )
        )
    deps = GraphDeps(
        db=db, llm=llm, crm=MockCRM(db), policy_admin=MockPolicyAdmin(db), billing=MockBilling(db)
    )
    state = await run_graph(
        run_id=run_id,
        use_case=use_case,
        subject_type=subject_type,
        subject_id=subject_id,
        cycle_key=cycle,
        deps=deps,
    )
    async with db.session() as s:
        (await s.get(Run, run_id)).status = "succeeded"
    rec = None
    if state.get("recommendation_id"):
        async with db.session() as s:
            rec = await s.get(Recommendation, state["recommendation_id"])
    return state, rec


REN = [
    # policy, action, channel, queue, drafted
    ("pol_p01", "payment_reminder", "intermediary", "retention", True),  # broker-owned
    ("pol_p02", "retention_offer", "email", "retention", True),
    ("pol_p03", "retention_offer", "email", "retention", True),
    ("pol_p05", "payment_reminder", "email", "retention", True),
    ("pol_p06", "reinstatement", "email", "retention", True),
    ("pol_p09", "internal_task", "internal", "retention", False),
    ("pol_p11", "retention_offer", "email", "retention", True),
    ("pol_p12", "retention_offer", "intermediary", "retention", True),  # group scheme
    ("pol_p13", "payment_reminder", "email", "retention", True),  # service team
    ("pol_p14", "plan_review", "email", "adviser", True),
    ("pol_p15", "reinstatement", "email", "adviser", True),
    ("pol_p16", "plan_review", "email", "adviser", True),
    ("pol_p18", "internal_task", "internal", "adviser", False),
]


@pytest.mark.parametrize(("policy_id", "action", "channel", "queue", "drafted"), REN)
async def test_renewal_branches(seeded_db, policy_id, action, channel, queue, drafted):
    llm, provider = fake_llm()
    _, rec = await run_subject(seeded_db, llm, "renewal", policy_id)
    assert (rec.action, rec.channel, rec.priority, rec.queue) == (action, channel, "high", queue)
    assert (rec.draft_message is not None) is drafted
    assert len(provider.calls) == (2 if drafted else 1)
    assert rec.expires_at is not None and rec.triggers and rec.lifecycle_type
    assert rec.cycle_key.startswith(policy_id + ":")


async def test_offer_and_draft_details(seeded_db):
    llm, _ = fake_llm()
    _, rec = await run_subject(seeded_db, llm, "renewal", "pol_p03")
    assert rec.offer["discount_pct"] == 5
    assert rec.offer["premium_after"] == round(1628400 * 0.95)
    assert rec.draft_message.startswith("Hi Grace,")
    assert "{first_name}" not in rec.draft_message
    assert rec.draft_subject == "Your policy"
    assert rec.decisions["message_draft"]["body"].startswith("Hi {first_name}")


async def test_draft_sees_only_its_action_facts(seeded_db):
    llm, provider = fake_llm()
    await run_subject(seeded_db, llm, "renewal", "pol_p13")
    draft = payload(next(c for c in provider.calls if c["purpose"] == "message_draft")["messages"])
    facts = draft["facts"]
    assert facts["premium_period"] == "monthly" and facts["amount_overdue"]
    assert not any(k.startswith("renewal_annual_premium") for k in facts)  # no renewal pricing
    assert draft["sign_off"] == "Your financial adviser"


async def test_broker_policy_draft_is_a_task_note(seeded_db):
    llm, provider = fake_llm()
    _, rec = await run_subject(seeded_db, llm, "renewal", "pol_p01")
    draft = payload(next(c for c in provider.calls if c["purpose"] == "message_draft")["messages"])
    assert draft["audience"] == "intermediary"
    assert rec.channel_owner == "broker" and rec.draft_subject


@pytest.mark.parametrize("policy_id", ["pol_p07", "pol_p08", "pol_p10", "pol_p17"])
async def test_renewal_skips_write_no_recommendation(seeded_db, policy_id):
    llm, provider = fake_llm()
    state, rec = await run_subject(seeded_db, llm, "renewal", policy_id)
    assert rec is None and state["gate"] == "skip"
    assert provider.calls == []


async def test_protected_info_never_reaches_llm(seeded_db):
    llm, provider = fake_llm()
    await run_subject(seeded_db, llm, "renewal", "pol_p03")
    async with seeded_db.session() as s:
        policy = await s.get(Policy, "pol_p03")
        customer = await s.get(Customer, policy.customer_id)
    personal = [customer.first_name, customer.last_name, customer.email, customer.city]
    assert provider.calls
    for call in provider.calls:
        data = payload(call["messages"])
        assert scan_payload(data) == []
        text = str(data).lower()
        for word in personal:
            assert word and not re.search(rf"{re.escape(word.lower())}", text), word


async def test_rerun_supersedes_pending(seeded_db):
    llm, _ = fake_llm()
    _, first = await run_subject(seeded_db, llm, "renewal", "pol_p03")
    _, second = await run_subject(seeded_db, llm, "renewal", "pol_p03")
    async with seeded_db.session() as s:
        old = await s.get(Recommendation, first.id)
        pending = len(
            s.where(
                Recommendation,
                lambda r: r.subject_id == "pol_p03" and r.status == "pending_approval",
            )
        )
    assert old.status == "superseded" and old.version == 2
    assert pending == 1 and second.status == "pending_approval"


async def test_llm_failure_propagates_and_writes_nothing(seeded_db):
    def down(purpose, messages):
        raise ProviderError("503", status=503, retryable=True)

    llm, _ = fake_llm(down)
    with pytest.raises(LLMUnavailable):
        await run_subject(seeded_db, llm, "renewal", "pol_p03")
    async with seeded_db.session() as s:
        n = len(s.all(Recommendation))
        calls = [c.status for c in s.all(LLMCall)]
    assert n == 0
    assert calls and set(calls) == {"error"}


async def test_audit_trail_per_node(seeded_db):
    llm, _ = fake_llm()
    state, rec = await run_subject(seeded_db, llm, "renewal", "pol_p03")
    async with seeded_db.session() as s:
        events = [
            e.event_type
            for e in sorted(s.all(AuditEvent), key=lambda e: e.id)
            if e.run_id == state["run_id"]
        ]
        llm_rows = [(c.node, c.purpose) for c in s.all(LLMCall) if c.run_id == state["run_id"]]
    assert events == [
        "node.renewal",
        "node.retention",
        "node.recommendation",
        "node.personalisation",
        "recommendation.created",
    ]
    assert sorted(llm_rows) == [
        ("personalisation", "message_draft"),
        ("retention", "lapse_risk"),
    ]


async def test_unknown_subject_raises(seeded_db):
    llm, _ = fake_llm()
    with pytest.raises(LookupError):
        await run_subject(seeded_db, llm, "renewal", "pol_nope")


async def test_graph_rejects_other_use_cases(seeded_db):
    llm, _ = fake_llm()
    with pytest.raises(ValueError, match="unsupported run"):
        await run_subject(seeded_db, llm, "acquisition", "pol_p03")


def _add_on_first(purpose, messages):
    out = smart_responder(purpose, messages)
    data = payload(messages)
    if purpose == "lapse_risk" and "add_on_offer" in data["allowed_actions"]:
        out |= {
            "intervention": "add_on_offer",
            "channel": data["marketing_channels"][0],
            "discount_pct": None,
        }
    return out


async def test_recommendation_agent_picks_the_extra_cover(seeded_db):
    llm, provider = fake_llm(_add_on_first)
    state, rec = await run_subject(seeded_db, llm, "renewal", "pol_p14")
    options = state["assessment"].add_on_options
    assert rec.action == "add_on_offer" and rec.queue == "adviser"  # adviser-led relationship
    assert rec.offer["type"] == "add_on" and rec.offer["code"] in options
    assert rec.offer["name"] and rec.offer["rationale"]
    used_llm = any(c["purpose"] == "add_on_fit" for c in provider.calls)
    assert used_llm is (len(options) > 1)
    assert ("add_on_fit" in rec.decisions) is used_llm


async def test_workflow_agent_attaches_portal_link(seeded_db):
    llm, _ = fake_llm()
    _, rec = await run_subject(seeded_db, llm, "renewal", "pol_p03")  # retention offer
    async with seeded_db.session() as s:
        number = (await s.get(Policy, "pol_p03")).policy_number
    assert rec.link == {
        "label": "Renew online",
        "url": f"https://portal.example.com/renew/{number}",
    }
    _, task = await run_subject(seeded_db, llm, "renewal", "pol_p09")  # internal task
    assert task.link is None


async def test_preferred_channel_is_used(seeded_db):
    async with seeded_db.session() as s:
        policy = await s.get(Policy, "pol_p05")
        (await s.get(Customer, policy.customer_id)).preferred_channel = "sms"
    llm, provider = fake_llm()
    _, rec = await run_subject(seeded_db, llm, "renewal", "pol_p05")
    lapse = payload(next(c for c in provider.calls if c["purpose"] == "lapse_risk")["messages"])
    assert lapse["preferred_channel"] == "sms" and lapse["service_channels"][0] == "sms"
    assert rec.channel == "sms"


async def test_cover_suggested_even_when_message_is_about_something_else(seeded_db):
    llm, _ = fake_llm()
    state, rec = await run_subject(seeded_db, llm, "renewal", "pol_p03")
    assert rec.action == "retention_offer" and rec.offer["type"] == "discount"
    assert state["assessment"].add_on_options
    assert rec.cover_suggestion["code"] in state["assessment"].add_on_options
    assert rec.cover_suggestion["name"] and rec.cover_suggestion["rationale"]


async def test_no_cover_suggestion_when_nothing_is_eligible(seeded_db):
    llm, _ = fake_llm()
    state, rec = await run_subject(seeded_db, llm, "renewal", "pol_p05")
    assert not state["assessment"].add_on_options and rec.cover_suggestion is None
