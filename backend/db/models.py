"""Stored records, one CSV file per class (``__table__``). Enum-valued fields hold the StrEnum
value (see ``backend.enums``).

Money is stored as integer minor units (cents). Dates are calendar dates; timestamps are UTC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from backend.db.store import Record
from backend.enums import ACTIVE_RUN_STATUSES, RecStatus
from backend.utils.clock import utcnow

model = dataclass(kw_only=True, eq=False)


def _dict() -> Any:
    return field(default_factory=dict)


def _list() -> Any:
    return field(default_factory=list)


# ---------------------------------------------------------------- domain ---


@model
class Customer(Record):
    __table__ = "customers"
    __unique__ = (("external_ref",),)

    id: str
    external_ref: str | None = None
    first_name: str
    last_name: str
    dob: date | None = None
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    consent_marketing: bool = False
    consent_email: bool = False
    consent_sms: bool = False
    consent_updated_at: datetime | None = None
    # Stated contact preference (email | sms); used whenever consent allows it.
    preferred_channel: str | None = None
    # Protected attributes: stored for record only, never sent to LLM or used by rules.
    protected: dict[str, Any] = _dict()
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@model
class Product(Record):
    __table__ = "products"
    __pk__ = "code"

    code: str
    line: str
    name: str
    description: str = ""
    min_age: int
    max_age: int
    min_sum_insured: int
    max_sum_insured: int
    base_premium: int  # annual, minor units
    max_discount_pct: int = 10
    tier: str = "standard"  # basic | standard | premium
    lifecycle_type: str = "expiry_renewal"
    payment_frequency: str = "annual"
    channels: list[Any] = _list()  # relationship owners allowed to sell it
    grace_days: int = 0
    regulated: bool = False  # suggestions = advice
    add_ons: list[Any] = _list()  # product codes offerable as extra cover
    active: bool = True


@model
class Policy(Record):
    __table__ = "policies"
    __unique__ = (("policy_number",),)

    id: str
    policy_number: str
    customer_id: str
    product_code: str
    line: str
    start_date: date
    end_date: date
    premium: int  # renewal (next-term) premium quote
    prev_premium: int  # current-term premium
    sum_insured: int
    status: str = "active"
    claims_count_3y: int = 0
    tenure_years: int = 0
    docs_outstanding: list[Any] = _list()
    auto_renew: bool = False
    service_complaints_12m: int = 0
    # Lifecycle contract (copied from the product at issue time).
    lifecycle_type: str = "expiry_renewal"
    payment_frequency: str = "annual"
    channel_owner: str = "direct"
    intermediary: str | None = None
    review_due_date: date | None = None
    milestone_date: date | None = None
    milestone_label: str | None = None
    add_ons_held: list[Any] = _list()
    # Next lifecycle event as last computed by the monitor (drives the worklist + cycle key).
    next_event_type: str | None = None
    next_event_date: date | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@model
class Payment(Record):
    __table__ = "payments"

    id: str
    policy_id: str
    due_date: date
    amount: int
    status: str
    paid_at: datetime | None = None


# ------------------------------------------------------------- execution ---


@model
class Batch(Record):
    __table__ = "batches"
    __persist__ = False  # groups one scan's runs; only needed while it is running

    id: str
    kind: str
    params: dict[str, Any] = _dict()
    skipped: list[Any] = _list()  # [{subject_id, reason}] filtered before queueing
    requested_by: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@model
class Run(Record):
    __table__ = "runs"
    __persist__ = False  # agent jobs; results live in recommendations / audit / CRM
    # At most one active run per subject (race guard for duplicate triggers / scans).
    __unique__ = (("subject_type", "subject_id"),)

    id: str
    batch_id: str | None = None
    use_case: str
    subject_type: str
    subject_id: str
    cycle_key: str
    status: str = "queued"
    attempts: int = 0
    max_attempts: int = 3
    claimed_by: str | None = None
    heartbeat_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    result: dict[str, Any] = _dict()
    requested_by: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def unique_scope(self, fields: tuple[str, ...]) -> bool:
        return self.status in ACTIVE_RUN_STATUSES


# ------------------------------------------------------------------ HITL ---


@model
class Recommendation(Record):
    __table__ = "recommendations"
    # At most one open recommendation per subject + lifecycle event.
    __unique__ = (("subject_type", "subject_id", "cycle_key"),)

    id: str
    run_id: str
    use_case: str
    subject_type: str
    subject_id: str
    cycle_key: str
    status: str = "pending_approval"
    version: int = 1
    queue: str
    priority: str
    action: str
    channel_owner: str | None = None
    lifecycle_type: str | None = None
    triggers: list[Any] = _list()  # lifecycle events that fired
    rulebook_version: str | None = None
    band: str | None = None
    confidence: str | None = None
    needs_review: bool = False
    review_reasons: list[Any] = _list()
    signals: dict[str, Any] = _dict()
    decisions: dict[str, Any] = _dict()  # LLM decisions by agent
    rule_results: list[Any] = _list()
    offer: dict[str, Any] | None = None
    # Best-suited extra cover for this customer ({code, name, rationale}), picked by the
    # recommendation agent whenever any add-on is eligible, even if the message is about
    # something else; an adviser raises it at the right time.
    cover_suggestion: dict[str, Any] | None = None
    channel: str | None = None
    # Customer portal link sent with the message ({"label", "url"}), e.g. a renewal link.
    link: dict[str, Any] | None = None
    draft_subject: str | None = None
    draft_message: str | None = None
    explanation: str | None = None
    fairness: dict[str, Any] = _dict()
    expires_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)
    decided_at: datetime | None = None
    decided_by: str | None = None

    def unique_scope(self, fields: tuple[str, ...]) -> bool:
        return self.status == RecStatus.PENDING_APPROVAL


@model
class Approval(Record):
    __table__ = "approvals"
    __unique__ = (("recommendation_id",),)

    id: str
    recommendation_id: str
    decision: str
    user_id: str
    actor_name: str
    actor_role: str
    session_id: str | None = None
    reason: str | None = None
    edits: dict[str, Any] = _dict()
    original_snapshot: dict[str, Any] = _dict()
    created_at: datetime = field(default_factory=utcnow)


@model
class Message(Record):
    """Outbox row. Exactly one per recommendation; sent by the workflow agent after approval."""

    __table__ = "messages"
    __unique__ = (("recommendation_id",),)

    id: str
    recommendation_id: str
    subject_type: str
    subject_id: str
    channel: str
    recipient: str | None = None
    body: str
    status: str = "queued"
    attempts: int = 0
    provider_ref: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    sent_at: datetime | None = None


@model
class CrmActivity(Record):
    """What the workflow agent wrote back to the CRM (one row per contact or status update)."""

    __table__ = "crm_activities"

    id: str
    customer_id: str | None = None
    policy_id: str | None = None
    recommendation_id: str | None = None
    kind: str  # message_delivered | follow_up_approved | follow_up_rejected | documents_received
    channel: str | None = None
    summary: str
    actor: str = "system"
    created_at: datetime = field(default_factory=utcnow)


# ---------------------------------------------------------------- audit ---


@model
class LLMCall(Record):
    __table__ = "llm_calls"
    __persist__ = False  # AI prompts and answers: kept in memory only, no file

    id: str
    run_id: str | None = None
    node: str | None = None
    purpose: str
    provider: str
    model: str
    attempt: int
    request: dict[str, Any] = _dict()
    response_raw: str | None = None
    parsed: dict[str, Any] | None = None
    status: str  # ok | error | invalid | pending | blocked
    error: str | None = None
    http_status: int | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    created_at: datetime = field(default_factory=utcnow)


@model
class AuditEvent(Record):
    """Append-only. Never updated or deleted by application code."""

    __table__ = "audit_events"

    id: int | None = None  # assigned on insert (1, 2, 3, ...)
    ts: datetime = field(default_factory=utcnow)
    event_type: str
    run_id: str | None = None
    recommendation_id: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    node: str | None = None
    actor: str = "system"
    payload: dict[str, Any] = _dict()


# ------------------------------------------------------------- identity ---


@model
class User(Record):
    __table__ = "users"
    __persist__ = False  # demo sign-in names; approvals keep the approver's name
    __unique__ = (("name_key",),)

    id: str
    name: str
    name_key: str  # casefolded name
    role: str
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@model
class Session(Record):
    __table__ = "sessions"
    __persist__ = False  # logins: pick a name again after a backend restart

    id: str
    user_id: str
    user_agent: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    last_seen_at: datetime = field(default_factory=utcnow)
    expires_at: datetime
    ended_at: datetime | None = None


# Parents before children: the load order of the CSV files.
MODELS = (
    Customer,
    Product,
    Policy,
    Payment,
    User,
    Session,
    Batch,
    Run,
    Recommendation,
    Approval,
    Message,
    CrmActivity,
    LLMCall,
    AuditEvent,
)
