"""Facts = the only inputs hard rules and LLM feature builders may see.

Built from ORM rows by ``renewal_facts``. They deliberately carry **no
protected attributes** (gender, religion, nationality, ...) and no city/postcode; a unit test
asserts this so a future field can't sneak in.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from backend.db.models import Customer, Payment, Policy, Product
from backend.enums import PaymentStatus


def age_at(dob: date | None, as_of: date) -> int | None:
    if dob is None:
        return None
    years = as_of.year - dob.year - ((as_of.month, as_of.day) < (dob.month, dob.day))
    return years


class AddOnCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    description: str
    min_age: int
    max_age: int


class RenewalFacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_id: str
    as_of: date
    line: str
    product_code: str
    product_name: str = ""
    policy_status: str
    lifecycle_type: str
    payment_frequency: str
    channel_owner: str
    start_date: date
    end_date: date
    premium: int
    prev_premium: int
    sum_insured: int
    tenure_years: int
    claims_count_3y: int
    docs_outstanding: list[str] = Field(default_factory=list)
    auto_renew: bool = False
    service_complaints_12m: int = 0
    overdue_payments: int = 0
    overdue_amount: int = 0
    failed_payments: int = 0
    oldest_overdue_due: date | None = None
    review_due_date: date | None = None
    milestone_date: date | None = None
    milestone_label: str | None = None
    customer_age: int | None = None
    has_email: bool = False
    has_phone: bool = False
    consent_marketing: bool = False
    consent_email: bool = False
    consent_sms: bool = False
    preferred_channel: str | None = None
    product_max_discount_pct: int = 0
    product_grace_days: int = 0
    product_regulated: bool = False
    add_ons_held: list[str] = Field(default_factory=list)
    add_on_candidates: list[AddOnCandidate] = Field(default_factory=list)


def renewal_facts(
    policy: Policy,
    customer: Customer,
    product: Product,
    payments: list[Payment],
    as_of: date,
    add_on_products: Iterable[Product] = (),
) -> RenewalFacts:
    overdue = [p for p in payments if p.status == PaymentStatus.OVERDUE]
    held = list(policy.add_ons_held or [])
    return RenewalFacts(
        policy_id=policy.id,
        as_of=as_of,
        line=policy.line,
        product_code=policy.product_code,
        product_name=product.name,
        policy_status=policy.status,
        lifecycle_type=policy.lifecycle_type or product.lifecycle_type,
        payment_frequency=policy.payment_frequency or product.payment_frequency,
        channel_owner=policy.channel_owner or "direct",
        start_date=policy.start_date,
        end_date=policy.end_date,
        premium=policy.premium,
        prev_premium=policy.prev_premium,
        sum_insured=policy.sum_insured,
        tenure_years=policy.tenure_years,
        claims_count_3y=policy.claims_count_3y,
        docs_outstanding=list(policy.docs_outstanding or []),
        auto_renew=policy.auto_renew,
        service_complaints_12m=policy.service_complaints_12m,
        overdue_payments=len(overdue),
        overdue_amount=sum(p.amount for p in overdue),
        failed_payments=sum(p.status == PaymentStatus.FAILED for p in payments),
        oldest_overdue_due=min((p.due_date for p in overdue), default=None),
        review_due_date=policy.review_due_date,
        milestone_date=policy.milestone_date,
        milestone_label=policy.milestone_label,
        customer_age=age_at(customer.dob, as_of),
        has_email=bool(customer.email),
        has_phone=bool(customer.phone),
        consent_marketing=customer.consent_marketing,
        consent_email=customer.consent_email,
        consent_sms=customer.consent_sms,
        preferred_channel=customer.preferred_channel,
        product_max_discount_pct=product.max_discount_pct,
        product_grace_days=product.grace_days,
        product_regulated=product.regulated,
        add_ons_held=held,
        add_on_candidates=[
            AddOnCandidate(
                code=p.code,
                name=p.name,
                description=p.description,
                min_age=p.min_age,
                max_age=p.max_age,
            )
            for p in add_on_products
            if p.code in (product.add_ons or []) and p.code not in held and p.active is not False
        ],
    )
