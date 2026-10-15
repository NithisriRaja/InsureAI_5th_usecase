from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.api.schemas.common import RecBrief, RunBrief


class ScanIn(BaseModel):
    window_days: int | None = Field(
        default=None, ge=1, le=365, description="Override the expiry notice window."
    )
    rerun_pending: bool = Field(
        default=False,
        description="Also re-run policies whose message is still waiting for approval "
        "(the new result replaces it). Already approved / rejected events are never re-run.",
    )


class RenewalItem(BaseModel):
    policy_id: str
    policy_number: str
    customer_name: str
    line: str
    product_code: str
    product_name: str
    lifecycle_type: str
    payment_frequency: str
    channel_owner: str
    intermediary: str | None
    status: str
    state: str  # due | in_grace | lapsed | skip (computed from the lifecycle rules)
    skip_reason: str | None
    triggers: list[str]
    next_event_type: str | None
    next_event_date: date | None
    end_date: date
    days_to_expiry: int | None  # expiry lifecycles only
    premium: int
    prev_premium: int
    premium_change_pct: float
    overdue_payments: int
    docs_outstanding: list[str]
    latest_recommendation: RecBrief | None
    active_run: RunBrief | None


class PaymentOut(BaseModel):
    due_date: date
    amount: int  # minor units
    status: str
    paid_at: datetime | None


class PolicyDetail(RenewalItem):
    """One policy as a reviewer sees it before running the lifecycle agents."""

    customer_id: str
    email: str | None
    phone: str | None
    city: str | None
    consent_marketing: bool
    consent_email: bool
    consent_sms: bool
    preferred_channel: str | None = None
    start_date: date
    sum_insured: int  # minor units
    tenure_years: int
    claims_count_3y: int
    auto_renew: bool
    service_complaints_12m: int
    review_due_date: date | None
    milestone_date: date | None
    milestone_label: str | None
    add_ons_held: list[str]
    trigger_details: list[dict[str, Any]]
    allowed_actions: list[str]
    in_window: bool
    payments: list[PaymentOut]
    latest_run: RunBrief | None


class DocumentsIn(BaseModel):
    received: list[str] = Field(min_length=1, description="Document codes now on file.")


class DocumentsOut(BaseModel):
    policy_id: str
    received: list[str]
    docs_outstanding: list[str]


class CrmActivityOut(BaseModel):
    id: str
    kind: str
    channel: str | None
    summary: str
    actor: str
    recommendation_id: str | None
    created_at: datetime
