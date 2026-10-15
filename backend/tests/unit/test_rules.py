from __future__ import annotations

import dataclasses
from datetime import date, timedelta

import pytest

from backend import rulebook
from backend.agents.shared import features
from backend.db.models import Customer, Product
from backend.enums import Action, Channel, Queue, Trigger
from backend.seed import PRODUCTS, _policy_objects, scenario_policies
from backend.services import guardrails
from backend.services.rules import fairness, renewal, routing
from backend.services.rules.facts import RenewalFacts, renewal_facts

AS_OF = date(2026, 10, 13)
CATALOGUE = [Product(**p) for p in PRODUCTS]
PRODUCTS_BY_CODE = {p.code: p for p in CATALOGUE}


def policy(ref_prefix: str) -> RenewalFacts:
    idx, spec = next(
        (i, s) for i, s in enumerate(scenario_policies()) if s.ref.startswith(ref_prefix)
    )
    cust, pol, pays = _policy_objects(spec, AS_OF, idx)
    product = PRODUCTS_BY_CODE[pol.product_code]
    add_ons = [PRODUCTS_BY_CODE[c] for c in product.add_ons]
    return renewal_facts(pol, cust, product, pays, AS_OF, add_ons)


# ------------------------------------------------------------- rulebook ---


def test_every_product_is_wired_to_the_rulebook() -> None:
    for p in PRODUCTS:
        assert p["line"] in rulebook.LINES, p["code"]
        assert p["lifecycle_type"] in rulebook.LIFECYCLES, p["code"]
        assert set(p["channels"]) <= set(rulebook.LINES[p["line"]]["owners"]), p["code"]
        for code in p["add_ons"]:
            assert rulebook.product(code) is not None, code


def test_premium_lifecycles_can_never_fire_expiry_triggers() -> None:
    for lt, cfg in rulebook.LIFECYCLES.items():
        if lt not in ("expiry_renewal", "group_scheme_renewal"):
            assert Trigger.UPCOMING_EXPIRY not in cfg["triggers"], lt
            assert Trigger.SCHEME_ANNIVERSARY not in cfg["triggers"], lt


def test_every_action_has_an_approver() -> None:
    for action in Action:
        assert action in rulebook.APPROVAL_MATRIX, action
        assert rulebook.APPROVAL_MATRIX[action]["agent"] in ("draft", "recommend")


# ---------------------------------------------------------------- routing ---


@pytest.mark.parametrize(
    ("action", "owner", "regulated", "queue"),
    [
        (Action.REMINDER, "direct", False, Queue.RETENTION),
        (Action.REMINDER, "adviser", True, Queue.ADVISER),
        (Action.PAYMENT_REMINDER, "adviser", True, Queue.RETENTION),
        (Action.ADD_ON_OFFER, "direct", False, Queue.RETENTION),
        (Action.ADD_ON_OFFER, "adviser", True, Queue.ADVISER),
        (Action.PLAN_REVIEW, "adviser", True, Queue.ADVISER),
    ],
)
def test_queue_routing(action, owner, regulated, queue) -> None:
    assert routing.route_queue(action, owner, regulated_product=regulated) == queue


# ---------------------------------------------------------------- renewal ---

RENEWAL_EXPECTATIONS = [
    ("P01", "due", {Action.REMINDER, Action.PAYMENT_REMINDER}),
    ("P02", "due", {Action.REMINDER, Action.DOCUMENT_REQUEST, Action.RETENTION_OFFER}),
    (
        "P03",
        "due",
        {
            Action.REMINDER,
            Action.SERVICE_FOLLOW_UP,
            Action.RETENTION_OFFER,
            Action.ADD_ON_OFFER,
        },
    ),
    ("P04", "due", {Action.REMINDER, Action.RETENTION_OFFER, Action.ADD_ON_OFFER}),
    ("P05", "in_grace", {Action.REMINDER, Action.PAYMENT_REMINDER}),
    ("P06", "lapsed", {Action.REINSTATEMENT}),
    ("P07", "skip", set()),
    ("P08", "skip", set()),
    ("P09", "due", {Action.INTERNAL_TASK}),
    ("P10", "skip", set()),
    ("P11", "due", {Action.REMINDER, Action.SERVICE_FOLLOW_UP, Action.RETENTION_OFFER}),
    ("P12", "due", {Action.REMINDER, Action.RETENTION_OFFER}),
    ("P13", "in_grace", {Action.PAYMENT_REMINDER}),
    ("P14", "due", {Action.PLAN_REVIEW, Action.ADD_ON_OFFER}),
    ("P15", "lapsed", {Action.REINSTATEMENT}),
    ("P16", "due", {Action.PLAN_REVIEW, Action.ADD_ON_OFFER}),
    ("P17", "skip", set()),
    ("P18", "due", {Action.INTERNAL_TASK}),
]


@pytest.mark.parametrize(("ref", "state", "actions"), RENEWAL_EXPECTATIONS)
def test_renewal_scenarios(ref, state, actions) -> None:
    a = renewal.assess(policy(ref))
    assert a.state == state, a.skip_reason
    assert set(a.allowed_actions) == actions


def test_skip_reasons() -> None:
    assert renewal.assess(policy("P07")).skip_reason == "already_renewed"
    assert renewal.assess(policy("P08")).skip_reason == "cancelled"
    assert renewal.assess(policy("P10")).skip_reason == "out_of_window"
    assert renewal.assess(policy("P17")).skip_reason == "no_trigger"


def test_premium_products_never_get_expiry_triggers() -> None:
    # P17's term ends in 20 days, inside any expiry window: still no expiry trigger.
    f = policy("P17")
    assert (f.end_date - AS_OF).days == 20
    assert renewal.assess(f).triggers == []
    for ref in ("P13", "P14", "P15", "P16", "P18"):
        types = {t.type for t in renewal.assess(policy(ref)).triggers}
        assert not types & {Trigger.UPCOMING_EXPIRY, Trigger.SCHEME_ANNIVERSARY}, ref


def test_trigger_types_by_lifecycle() -> None:
    def types(ref: str) -> set[str]:
        return {t.type.value for t in renewal.assess(policy(ref)).triggers}

    assert types("P02") == {"upcoming_expiry", "missing_document"}
    assert types("P12") == {"scheme_anniversary"}
    assert types("P13") == {"premium_missed"}
    assert types("P14") == {"scheduled_review"}
    assert types("P15") == {"premium_missed", "lapse_risk_signal"}
    assert types("P16") == {"milestone"}


def test_notice_window_override_applies_to_one_year_terms_only() -> None:
    assert renewal.assess(policy("P10"), 100).state == "due"
    assert renewal.assess(policy("P12"), 30).state == "due"  # group keeps its 90 days


@pytest.mark.parametrize(
    ("product", "days_past", "state"),
    [
        ("MOTOR_TPL", 0, "due"),  # expires today
        ("MOTOR_TPL", 1, "lapsed"),  # motor has no grace
        ("HOME_CONTENTS", 15, "in_grace"),
        ("HOME_CONTENTS", 16, "lapsed"),
        ("MEDICAL_ESSENTIAL", 30, "in_grace"),
        ("MEDICAL_ESSENTIAL", 61, "skip"),  # beyond reinstatement lookback
    ],
)
def test_grace_boundaries(product, days_past, state) -> None:
    grace = PRODUCTS_BY_CODE[product].grace_days
    f = policy("P04").model_copy(
        update={"product_grace_days": grace, "end_date": AS_OF - timedelta(days=days_past)}
    )
    assert renewal.lifecycle_state(f)[0] == state


@pytest.mark.parametrize(
    ("overdue_days", "state"),
    [(10, "in_grace"), (30, "in_grace"), (31, "lapsed"), (90, "lapsed"), (91, "skip")],
)
def test_premium_grace_boundaries(overdue_days, state) -> None:
    f = policy("P13").model_copy(
        update={"oldest_overdue_due": AS_OF - timedelta(days=overdue_days)}
    )
    assert renewal.lifecycle_state(f)[0] == state


def test_stored_status_lag_is_ignored() -> None:
    # Stored "active" but calendar says lapsed -> treat as lapsed.
    f = policy("P04").model_copy(update={"end_date": AS_OF - timedelta(days=5)})
    assert renewal.lifecycle_state(f)[0] == "lapsed"


def test_p03_price_shock_signal_and_cap() -> None:
    a = renewal.assess(policy("P03"))
    assert a.signals["premium_change_pct"] == 18.0
    assert a.max_discount_pct == 12
    assert a.add_on_options == ["PA_INDIVIDUAL"]


def test_expiry_includes_grace() -> None:
    a = renewal.assess(policy("P05"))
    assert a.expires_at is not None
    assert a.expires_at.date() == date(2026, 10, 3) + timedelta(days=30)


def test_cycle_key_follows_the_event() -> None:
    assert renewal.assess(policy("P02")).cycle_key_suffix == "upcoming_expiry:2026-11-12"
    a = renewal.assess(policy("P13"))
    assert a.cycle_key_suffix == f"premium_missed:{AS_OF - timedelta(days=20)}"


@pytest.mark.parametrize(
    ("action", "channel", "discount", "errors"),
    [
        ("retention_offer", "email", 10, set()),
        ("retention_offer", "email", 12, set()),
        ("retention_offer", "email", 13, {"renewal.discount_cap"}),
        ("retention_offer", "email", None, {"renewal.offer_discount_missing"}),
        ("reminder", "sms", None, set()),
        ("reminder", "sms", 5, {"renewal.discount_without_offer"}),
        ("reinstatement", "email", None, {"renewal.action_not_allowed"}),
        ("reminder", "whatsapp", None, {"consent.channel"}),
        ("reminder", "intermediary", None, {"consent.channel"}),
    ],
)
def test_validate_intervention(action, channel, discount, errors) -> None:
    a = renewal.assess(policy("P03"))
    errs = renewal.validate_intervention(a, action=action, channel=channel, discount_pct=discount)
    assert {e.id for e in errs} == errors


def test_add_on_must_be_suitable() -> None:
    a = renewal.assess(policy("P03"))
    ok = renewal.validate_intervention(
        a, action="add_on_offer", channel="email", discount_pct=None, add_on_code="PA_INDIVIDUAL"
    )
    assert ok == []
    bad = renewal.validate_intervention(
        a, action="add_on_offer", channel="email", discount_pct=None, add_on_code="LIFE_TERM"
    )
    assert {e.id for e in bad} == {"suitability.add_on"}


def test_broker_owned_policy_only_gets_intermediary_tasks() -> None:
    a = renewal.assess(policy("P01"))
    assert a.service_channels == [Channel.INTERMEDIARY]
    assert a.marketing_channels == [Channel.INTERMEDIARY]
    errs = renewal.validate_intervention(a, action="reminder", channel="email", discount_pct=None)
    assert {e.id for e in errs} == {"consent.channel"}


def test_no_consent_only_internal_task() -> None:
    a = renewal.assess(policy("P09"))
    assert a.service_channels == []
    assert (
        renewal.validate_intervention(
            a, action="internal_task", channel="internal", discount_pct=None
        )
        == []
    )
    errs = renewal.validate_intervention(
        a, action="internal_task", channel="email", discount_pct=None
    )
    assert {e.id for e in errs} == {"consent.channel"}


def test_offer_needs_marketing_consent() -> None:
    f = policy("P03").model_copy(update={"consent_marketing": False})
    a = renewal.assess(f)
    assert Action.RETENTION_OFFER not in a.allowed_actions
    assert Action.ADD_ON_OFFER not in a.allowed_actions
    assert a.service_channels == [Channel.EMAIL, Channel.SMS, Channel.EMAIL_SMS]


def test_no_discounts_on_premium_products() -> None:
    f = policy("P14").model_copy(update={"product_max_discount_pct": 10})
    assert Action.RETENTION_OFFER not in renewal.assess(f).allowed_actions


# ------------------------------------------------------------- guardrails ---


@pytest.mark.parametrize(
    ("rec", "rule"),
    [
        ({"action": "decline"}, "guardrail.forbidden_action"),
        ({"action": "issue_policy"}, "guardrail.forbidden_action"),
        ({"action": "teleport"}, "guardrail.unknown_action"),
        (
            {"action": "reminder", "channel": "email", "channel_owner": "broker"},
            "guardrail.bypass_intermediary",
        ),
        (
            {"action": "reminder", "offer": {"discount_pct": 5, "max_discount_pct": 10}},
            "guardrail.pricing",
        ),
        (
            {"action": "retention_offer", "offer": {"discount_pct": 20, "max_discount_pct": 10}},
            "guardrail.pricing",
        ),
        ({"action": "reminder", "status": "approved"}, "guardrail.auto_execute"),
    ],
)
def test_guardrails_block(rec, rule) -> None:
    with pytest.raises(guardrails.GuardrailViolation) as e:
        guardrails.check_recommendation(rec)
    assert e.value.rule == rule


def test_guardrails_allow_valid() -> None:
    guardrails.check_recommendation(
        {"action": "reminder", "channel": "intermediary", "channel_owner": "broker"}
    )
    guardrails.check_recommendation(
        {
            "action": "retention_offer",
            "channel": "email",
            "channel_owner": "direct",
            "offer": {"discount_pct": 5, "max_discount_pct": 10},
            "status": "pending_approval",
        }
    )


# --------------------------------------------------------------- fairness ---


def test_facts_carry_no_protected_fields() -> None:
    assert not set(RenewalFacts.model_fields) & fairness.PROTECTED_KEYS


def test_customer_protected_data_not_in_renewal_facts() -> None:
    assert "protected" in {f.name for f in dataclasses.fields(Customer)}
    assert "protected" not in RenewalFacts.model_fields


def test_notes_redaction() -> None:
    notes, report = fairness.redact_text(
        "Customer mentioned she is a practising Catholic, recently divorced, "
        "originally from Poland. Wants to keep the cover."
    )
    assert notes is not None
    for word in ("Catholic", "divorced", "Poland", "she", "practising"):
        assert word.lower() not in notes.lower()
    assert report.redactions >= 4
    assert {"religion", "marital_status", "nationality", "gender"} <= set(report.categories)
    assert fairness.scan_payload({"notes": notes}) == []


def test_scan_payload_flags_keys_and_terms() -> None:
    v = fairness.scan_payload({"signals": {"gender": "f"}, "notes": "He is Muslim"})
    assert any("protected key" in x for x in v)
    assert any("religion" in x for x in v)
    with pytest.raises(fairness.FairnessViolation):
        fairness.assert_clean({"x": ["originally from Mexico"]})


def test_scan_avoids_substring_false_positives() -> None:
    assert fairness.scan_payload({"notes": "Other details: the mileage is low, thermal"}) == []


@pytest.mark.parametrize("ref", [s.ref[:3] for s in scenario_policies()])
def test_renewal_signals_are_clean(ref) -> None:
    f = policy(ref)
    signals = features.renewal_signals(f, renewal.assess(f).signals)
    assert fairness.scan_payload({"signals": signals}) == []


def test_age_band() -> None:
    assert features.age_band(17) == "under_18"
    assert features.age_band(34) == "25-34"
    assert features.age_band(80) == "75+"
    assert features.age_band(None) is None


def test_email_sms_only_when_both_channels_consented() -> None:
    both = policy("P03").model_copy(update={"consent_marketing": False})
    a = renewal.assess(both)
    assert Channel.EMAIL_SMS in a.service_channels
    assert not renewal.validate_intervention(
        a, action=Action.REMINDER, channel=Channel.EMAIL_SMS, discount_pct=None, add_on_code=None
    )
    email_only = both.model_copy(update={"consent_sms": False})
    a = renewal.assess(email_only)
    assert a.service_channels == [Channel.EMAIL]
    errs = renewal.validate_intervention(
        a, action=Action.REMINDER, channel=Channel.EMAIL_SMS, discount_pct=None, add_on_code=None
    )
    assert [e.id for e in errs] == ["consent.channel"]
