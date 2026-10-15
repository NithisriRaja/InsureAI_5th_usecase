"""Synthetic data: handcrafted edge-case scenarios plus Faker bulk data.

One mixed book of business: general lines sold direct or through brokers (expiry-driven
renewals), life and savings sold through advisers (premium continuation, reviews,
milestones) and employee-benefit schemes through brokers. The product catalogue lives in
``rulebook.PRODUCTS``.

All dates are relative to ``clock.today()`` so the data never goes stale; set AS_OF_DATE
for fully reproducible output. Money is in minor units (fils / cents).
"""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

from faker import Faker

from backend import rulebook
from backend.db.models import Customer, Payment, Policy, Product
from backend.db.store import DbSession
from backend.enums import (
    EXPIRY_LIFECYCLES,
    ChannelOwner,
    Line,
    PaymentFrequency,
    PaymentStatus,
    PolicyStatus,
)
from backend.rulebook import money
from backend.utils.clock import today, utcnow
from backend.utils.normalize import norm_phone

SEED = 42
K = rulebook.K
PRODUCTS = rulebook.PRODUCTS

BROKERS = ("Harbour Insurance Brokers", "Northgate Risk Partners", "Tidewater Brokerage")
ADVISERS = ("Omar Haddad", "Leena Rao", "James Whitfield")
CITIES = ("Dubai", "Abu Dhabi", "Sharjah", "Ajman")
POLICY_PREFIX = {
    Line.MOTOR: "MOT",
    Line.MEDICAL: "MED",
    Line.HOME: "HOM",
    Line.PERSONAL_ACCIDENT: "PAC",
    Line.LIFE: "LIF",
    Line.SAVINGS: "SAV",
    Line.GROUP: "GRP",
}


def _dob(age: int, as_of: date) -> date:
    return date(as_of.year - age, 6, 15) if as_of.month > 6 else date(as_of.year - age - 1, 6, 15)


# ------------------------------------------------------------- scenarios ---


@dataclass
class PolicySpec:
    ref: str
    first: str
    last: str
    age: int
    product: str
    prev_premium: int
    premium: int
    sum_insured: int
    end_offset_days: int | None = None  # expiry lifecycles: end of the current term
    status: PolicyStatus = PolicyStatus.ACTIVE
    tenure: int = 2
    claims: int = 0
    docs: list[str] = field(default_factory=list)
    overdue_installments: int = 0  # expiry lifecycles
    monthly: bool = False  # expiry lifecycles paid in instalments
    overdue_days: int = 0  # premium lifecycles: days since the oldest missed premium
    failed_payments: int = 0
    auto_renew: bool = False
    complaints: int = 0
    consent_email: bool = True
    consent_sms: bool = True
    consent_marketing: bool = True
    preferred_channel: str | None = None  # email | sms
    email: str | None = None
    phone: str | None = None
    channel_owner: str = ChannelOwner.DIRECT
    intermediary: str | None = None
    term_years: int = 20
    term_end_offset_days: int | None = None  # premium lifecycles: override the term end
    review_offset_days: int | None = None
    milestone_offset_days: int | None = None
    milestone_label: str | None = None
    add_ons_held: list[str] = field(default_factory=list)


def scenario_policies() -> list[PolicySpec]:
    return [
        # --- expiry-driven general lines
        PolicySpec(
            "P01-motor-broker-overdue",
            "Liam",
            "Murphy",
            31,
            "MOTOR_COMPREHENSIVE",
            money(3_150),
            money(3_400),
            money(110_000),
            end_offset_days=10,
            tenure=1,
            claims=1,
            overdue_installments=2,
            monthly=True,
            channel_owner=ChannelOwner.BROKER,
            intermediary=BROKERS[0],
        ),
        PolicySpec(
            "P02-home-docs",
            "Olivia",
            "Nguyen",
            44,
            "HOME_CONTENTS",
            money(640),
            money(660),
            money(260_000),
            end_offset_days=30,
            tenure=3,
            docs=["proof_of_address", "contents_valuation"],
        ),
        PolicySpec(
            "P03-medical-loyal-price-shock",
            "Grace",
            "Adeyemi",
            45,
            "MEDICAL_FAMILY",
            money(13_800),
            money(16_284),
            money(1_500_000),
            end_offset_days=20,
            tenure=6,
            email="grace.adeyemi@example.com",
            phone="+971 50 100 0203",
        ),
        PolicySpec(
            "P04-motor-low-risk",
            "Henry",
            "Svensson",
            50,
            "MOTOR_TPL",
            money(950),
            money(950),
            money(40_000),
            end_offset_days=40,
            tenure=8,
            auto_renew=True,
        ),
        PolicySpec(
            "P05-medical-in-grace",
            "Mia",
            "Rossi",
            36,
            "MEDICAL_ESSENTIAL",
            money(4_700),
            money(4_900),
            money(500_000),
            end_offset_days=-10,
            status=PolicyStatus.GRACE,
            tenure=2,
            overdue_installments=1,
        ),
        PolicySpec(
            "P06-motor-lapsed",
            "Ethan",
            "Brown",
            27,
            "MOTOR_TPL",
            money(1_000),
            money(1_080),
            money(30_000),
            end_offset_days=-20,
            status=PolicyStatus.LAPSED,
            tenure=1,
            overdue_installments=1,
        ),
        PolicySpec(
            "P07-motor-already-renewed",
            "Chloe",
            "Martin",
            40,
            "MOTOR_COMPREHENSIVE",
            money(2_900),
            money(2_950),
            money(120_000),
            end_offset_days=15,
            status=PolicyStatus.RENEWED,
            tenure=4,
        ),
        PolicySpec(
            "P08-home-cancelled",
            "Lucas",
            "Silva",
            55,
            "HOME_BUILDINGS_CONTENTS",
            money(2_300),
            money(2_400),
            money(3_200_000),
            end_offset_days=20,
            status=PolicyStatus.CANCELLED,
            tenure=5,
        ),
        PolicySpec(
            "P09-medical-no-contact-consent",
            "Zara",
            "Ahmed",
            33,
            "MEDICAL_ESSENTIAL",
            money(4_500),
            money(4_650),
            money(300_000),
            end_offset_days=12,
            tenure=2,
            consent_email=False,
            consent_sms=False,
            consent_marketing=False,
        ),
        PolicySpec(
            "P10-motor-out-of-window",
            "Oscar",
            "Novak",
            48,
            "MOTOR_TPL",
            money(920),
            money(940),
            money(35_000),
            end_offset_days=90,
            tenure=3,
        ),
        PolicySpec(
            "P11-home-expires-today-complaints",
            "Ava",
            "Kim",
            61,
            "HOME_BUILDINGS_CONTENTS",
            money(2_200),
            money(2_750),
            money(2_500_000),
            end_offset_days=0,
            tenure=4,
            complaints=2,
        ),
        PolicySpec(
            "P12-group-medical-broker",
            "Gulfline Logistics",
            "LLC",
            40,
            "GROUP_MEDICAL",
            money(180_000),
            money(189_000),
            money(2_000_000),
            end_offset_days=75,
            tenure=3,
            channel_owner=ChannelOwner.BROKER,
            intermediary=BROKERS[1],
            email="hr@gulfline-logistics.example.com",
            phone="+971 4 300 0117",
        ),
        # --- adviser-led life & savings (no annual expiry)
        PolicySpec(
            "P13-term-life-missed-premium",
            "Hassan",
            "Ali",
            41,
            "LIFE_TERM",
            money(3_600),
            money(3_600),
            money(2_000_000),
            tenure=4,
            overdue_days=20,
            channel_owner=ChannelOwner.ADVISER,
            intermediary=ADVISERS[0],
            review_offset_days=150,
        ),
        PolicySpec(
            "P14-whole-of-life-review-due",
            "Aisha",
            "Rahman",
            38,
            "LIFE_WHOLE_OF_LIFE",
            money(18_000),
            money(18_000),
            money(3_000_000),
            tenure=3,
            term_years=50,
            channel_owner=ChannelOwner.ADVISER,
            intermediary=ADVISERS[1],
            review_offset_days=20,
        ),
        PolicySpec(
            "P15-savings-lapsed",
            "Karan",
            "Mehta",
            33,
            "SAVINGS_REGULAR",
            money(12_000),
            money(12_000),
            money(250_000),
            tenure=2,
            overdue_days=45,
            failed_payments=1,
            term_years=15,
            channel_owner=ChannelOwner.ADVISER,
            intermediary=ADVISERS[2],
            review_offset_days=200,
        ),
        PolicySpec(
            "P16-education-milestone",
            "Noura",
            "Saeed",
            47,
            "SAVINGS_EDUCATION",
            money(24_000),
            money(24_000),
            money(400_000),
            tenure=9,
            term_years=10,
            channel_owner=ChannelOwner.ADVISER,
            intermediary=ADVISERS[0],
            milestone_offset_days=45,
            milestone_label="First university fee payment",
            review_offset_days=120,
        ),
        PolicySpec(
            "P17-term-life-all-clear",
            "Peter",
            "Walsh",
            59,
            "LIFE_TERM",
            money(4_800),
            money(4_800),
            money(1_000_000),
            tenure=15,
            channel_owner=ChannelOwner.ADVISER,
            intermediary=ADVISERS[1],
            term_end_offset_days=20,  # term ends soon: still no expiry-renewal trigger
            review_offset_days=200,
        ),
        PolicySpec(
            "P18-wealth-review-no-consent",
            "Sofia",
            "Lindgren",
            66,
            "SAVINGS_SINGLE_PREMIUM",
            money(250_000),
            money(250_000),
            money(250_000),
            tenure=5,
            term_years=10,
            channel_owner=ChannelOwner.ADVISER,
            intermediary=ADVISERS[2],
            review_offset_days=-10,
            consent_email=False,
            consent_sms=False,
            consent_marketing=False,
        ),
    ]


# --------------------------------------------------------------- builders ---


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def _policy_objects(
    spec: PolicySpec, as_of: date, idx: int
) -> tuple[Customer, Policy, list[Payment]]:
    prod = rulebook.product(spec.product)
    assert prod is not None, spec.product
    line = Line(prod["line"])
    expiry = prod["lifecycle_type"] in EXPIRY_LIFECYCLES
    code = spec.ref.split("-")[0]
    cust_id = f"cust_{code.lower()}"
    email = spec.email or _ascii_email(f"{spec.first}.{spec.last}.{idx}")
    customer = Customer(
        id=cust_id,
        external_ref=f"C-{code}",
        first_name=spec.first,
        last_name=spec.last,
        dob=_dob(spec.age, as_of),
        email=email,
        phone=norm_phone(spec.phone or f"+971 55 {200 + idx // 100:03d} {idx % 10000:04d}"),
        city=CITIES[idx % len(CITIES)],
        consent_marketing=spec.consent_marketing,
        consent_email=spec.consent_email,
        consent_sms=spec.consent_sms,
        preferred_channel=spec.preferred_channel,
        consent_updated_at=utcnow(),
    )
    if expiry:
        end = as_of + timedelta(days=spec.end_offset_days or 0)
        start = end - timedelta(days=365)
    else:
        start = _add_years(as_of, -spec.tenure) - timedelta(days=37 + idx % 50)
        end = (
            as_of + timedelta(days=spec.term_end_offset_days)
            if spec.term_end_offset_days is not None
            else _add_years(start, spec.term_years)
        )
    policy = Policy(
        id=f"pol_{code.lower()}",
        policy_number=f"{POLICY_PREFIX[line]}-{start.year}-{1000 + idx:05d}",
        customer_id=cust_id,
        product_code=spec.product,
        line=line.value,
        start_date=start,
        end_date=end,
        premium=spec.premium,
        prev_premium=spec.prev_premium,
        sum_insured=spec.sum_insured,
        status=spec.status.value,
        claims_count_3y=spec.claims,
        tenure_years=spec.tenure,
        docs_outstanding=spec.docs,
        auto_renew=spec.auto_renew,
        service_complaints_12m=spec.complaints,
        lifecycle_type=prod["lifecycle_type"].value,
        payment_frequency=prod["payment_frequency"].value,
        channel_owner=str(spec.channel_owner),
        intermediary=spec.intermediary,
        review_due_date=(
            as_of + timedelta(days=spec.review_offset_days)
            if spec.review_offset_days is not None
            else None
        ),
        milestone_date=(
            as_of + timedelta(days=spec.milestone_offset_days)
            if spec.milestone_offset_days is not None
            else None
        ),
        milestone_label=spec.milestone_label,
        add_ons_held=spec.add_ons_held,
    )
    if expiry:
        payments = _term_payments(policy, spec, as_of)
    elif prod["payment_frequency"] == PaymentFrequency.SINGLE:
        payments = [_payment(policy, 0, policy.start_date, spec.prev_premium, PaymentStatus.PAID)]
    else:
        payments = _monthly_premiums(policy, spec, as_of)
    return customer, policy, payments


def _payment(policy: Policy, n: int, due: date, amount: int, status: PaymentStatus) -> Payment:
    return Payment(
        id=f"pay_{policy.id}_{n:02d}",
        policy_id=policy.id,
        due_date=due,
        amount=amount,
        status=status.value,
        paid_at=utcnow() if status == PaymentStatus.PAID else None,
    )


def _term_payments(policy: Policy, spec: PolicySpec, as_of: date) -> list[Payment]:
    """Fixed-term products: one annual payment, or monthly instalments over the term."""
    if not spec.monthly:
        status = PaymentStatus.OVERDUE if spec.overdue_installments else PaymentStatus.PAID
        return [_payment(policy, 0, policy.start_date, spec.prev_premium, status)]
    out: list[Payment] = []
    due, n = policy.start_date, 0
    while due <= as_of and n < 12:
        out.append(_payment(policy, n, due, spec.prev_premium // 12, PaymentStatus.PAID))
        due, n = due + timedelta(days=30), n + 1
    for p in out[len(out) - spec.overdue_installments :] if spec.overdue_installments else []:
        p.status, p.paid_at = PaymentStatus.OVERDUE.value, None
    return out


def _monthly_premiums(policy: Policy, spec: PolicySpec, as_of: date) -> list[Payment]:
    """Premium-continuation products: the last 12 monthly premiums. Missed ones are overdue
    from ``overdue_days`` ago; ``failed_payments`` marks the latest paid ones as failed."""
    amount = spec.prev_premium // 12
    anchor = as_of - timedelta(days=spec.overdue_days or 5)
    dues = [anchor - timedelta(days=30 * k) for k in range(11, 0, -1)]
    missed = []
    d = anchor
    while d <= as_of and len(dues) + len(missed) < 12:
        missed.append(d)
        d += timedelta(days=30)
    if not spec.overdue_days:
        dues, missed = dues + missed, []
    out = [_payment(policy, n, due, amount, PaymentStatus.PAID) for n, due in enumerate(dues)]
    for p in out[len(out) - spec.failed_payments :] if spec.failed_payments else []:
        p.status, p.paid_at = PaymentStatus.FAILED.value, None
    out += [
        _payment(policy, len(dues) + n, due, amount, PaymentStatus.OVERDUE)
        for n, due in enumerate(missed)
    ]
    return out


# ---------------------------------------------------------------- faker ---

FAKE_LOCALES = ["en_US", "en_GB", "en_IN", "ar_AE", "fr_FR"]


def _ascii_email(local: str) -> str:
    ascii_local = unicodedata.normalize("NFKD", local).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9.]", "", ascii_local.lower()) + "@example.com"


def _fake_policy_spec(fake: Faker, rng: random.Random, i: int) -> PolicySpec:
    prod = rng.choice([p for p in PRODUCTS if p["code"] != "PA_INDIVIDUAL"])
    expiry = prod["lifecycle_type"] in EXPIRY_LIFECYCLES
    prev = prod["base_premium"] + money(rng.randint(0, 6) * 100)
    change = rng.choice([0, 0, 3, 5, 8, 12, 20, 30]) if expiry else 0
    owners = prod["channels"]
    owner = rng.choice(owners)
    first, last = fake.first_name(), fake.last_name()
    if prod["line"] == Line.GROUP:
        first, last = fake.company(), "LLC"
    spec = PolicySpec(
        ref=f"PF{i:03d}-{prod['line'].value}",
        first=first,
        last=last,
        age=rng.randint(max(prod["min_age"], 18) + 1, min(prod["max_age"], 70) - 1),
        product=prod["code"],
        prev_premium=prev,
        premium=prev * (100 + change) // 100,
        sum_insured=rng.randint(prod["min_sum_insured"], prod["max_sum_insured"]) // K * K,
        tenure=rng.choice([1, 1, 2, 3, 5, 8, 12]),
        claims=rng.choice([0, 0, 0, 1, 2]),
        docs=rng.choice([[], [], [], ["proof_of_address"], ["id_document"]]),
        auto_renew=rng.random() < 0.3,
        complaints=rng.choice([0, 0, 0, 1, 2]),
        consent_email=rng.random() > 0.1,
        consent_sms=rng.random() > 0.3,
        consent_marketing=rng.random() > 0.2,
        preferred_channel=rng.choice([None, None, "email", "sms"]),
        channel_owner=owner,
        intermediary=(
            rng.choice(ADVISERS)
            if owner == ChannelOwner.ADVISER
            else rng.choice(BROKERS)
            if owner in (ChannelOwner.BROKER, ChannelOwner.EMPLOYER)
            else None
        ),
    )
    if expiry:
        spec.end_offset_days = rng.randint(-25, 120)
        spec.overdue_installments = rng.choice([0, 0, 0, 0, 1, 2])
        spec.monthly = rng.random() < 0.4
    else:
        spec.overdue_days = rng.choice([0, 0, 0, 0, 0, 10, 25, 50])
        spec.failed_payments = rng.choice([0, 0, 0, 1])
        spec.term_years = rng.choice([10, 15, 20, 25])
        spec.review_offset_days = rng.randint(-20, 300)
        if prod["lifecycle_type"] == "milestone":
            spec.milestone_offset_days = rng.randint(10, 400)
            spec.milestone_label = "Education fund payout"
    return spec


# ------------------------------------------------------------------ main ---

SIZES = {"small": 0, "full": 80}  # target total policies


async def seed(s: DbSession, size: str = "small") -> dict[str, int]:
    from backend.services import lifecycle  # late import: services import the graph

    as_of = today()
    s.add_all(Product(**p) for p in PRODUCTS)

    customers: list[Customer] = []
    policies: list[Policy] = []
    payments: list[Payment] = []
    for idx, spec in enumerate(scenario_policies()):
        c, p, pays = _policy_objects(spec, as_of, idx)
        customers.append(c)
        policies.append(p)
        payments.extend(pays)

    target_policies = SIZES[size]
    if target_policies:
        fake = Faker(FAKE_LOCALES)
        Faker.seed(SEED)
        rng = random.Random(SEED)
        for i in range(max(0, target_policies - len(policies))):
            c, p, pays = _policy_objects(_fake_policy_spec(fake, rng, i), as_of, 100 + i)
            customers.append(c)
            policies.append(p)
            payments.extend(pays)

    s.add_all(customers)
    await s.flush()
    s.add_all(policies)
    await s.flush()
    s.add_all(payments)
    await s.flush()
    # Lifecycle monitor's first pass: store each policy's next event.
    for p in policies:
        a = await lifecycle.assess_policy(s, p)
        if a is not None:
            lifecycle.record_next_event(p, a)
    return {
        "products": len(PRODUCTS),
        "customers": len(customers),
        "policies": len(policies),
        "payments": len(payments),
    }
