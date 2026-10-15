"""Shared string enums used by DB models, rules, graph and API."""

from __future__ import annotations

from enum import StrEnum


class Line(StrEnum):
    # General insurance (broker + direct distribution, annual expiry-driven renewals)
    MOTOR = "motor"
    MEDICAL = "medical"
    HOME = "home"
    PERSONAL_ACCIDENT = "personal_accident"
    # Life, savings (adviser-led, premium continuation / reviews / milestones)
    LIFE = "life"
    SAVINGS = "savings"
    # Employee benefits (broker / employer, scheme-anniversary renewals)
    GROUP = "group"


class LifecycleType(StrEnum):
    """How a policy stays in force; decides which lifecycle triggers may fire."""

    EXPIRY_RENEWAL = "expiry_renewal"  # fixed term, renew at expiry
    GROUP_SCHEME_RENEWAL = "group_scheme_renewal"  # employer scheme anniversary
    PREMIUM_CONTINUATION = "premium_continuation"  # in force while premiums are paid
    SCHEDULED_REVIEW = "scheduled_review"  # single premium, periodic review
    MILESTONE = "milestone"  # premiums + a planned milestone (e.g. education payout)


EXPIRY_LIFECYCLES = (LifecycleType.EXPIRY_RENEWAL, LifecycleType.GROUP_SCHEME_RENEWAL)


class ChannelOwner(StrEnum):
    """Who owns the customer relationship. Outreach must go through the owner."""

    ADVISER = "adviser"
    BROKER = "broker"
    DIRECT = "direct"
    EMPLOYER = "employer"


INTERMEDIARY_OWNERS = (ChannelOwner.BROKER, ChannelOwner.EMPLOYER)


class PaymentFrequency(StrEnum):
    ANNUAL = "annual"
    MONTHLY = "monthly"
    SINGLE = "single"


class UseCase(StrEnum):
    RENEWAL = "renewal"


class SubjectType(StrEnum):
    POLICY = "policy"


class PolicyStatus(StrEnum):
    ACTIVE = "active"
    GRACE = "grace"
    LAPSED = "lapsed"
    RENEWED = "renewed"
    CANCELLED = "cancelled"


class PaymentStatus(StrEnum):
    PAID = "paid"
    DUE = "due"
    OVERDUE = "overdue"
    FAILED = "failed"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


ACTIVE_RUN_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING)
TERMINAL_RUN_STATUSES = (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.SKIPPED)


class BatchKind(StrEnum):
    RENEWAL_SCAN = "renewal_scan"


class RecStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    APPROVED_WITH_EDITS = "approved_with_edits"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


class Decision(StrEnum):
    APPROVED = "approved"
    APPROVED_WITH_EDITS = "approved_with_edits"
    REJECTED = "rejected"


class Queue(StrEnum):
    ADVISER = "adviser"  # adviser-led relationships, regulated advice
    RETENTION = "retention"  # service team


class Role(StrEnum):
    ADVISER = "adviser"
    RETENTION = "retention"
    ADMIN = "admin"


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Channel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    EMAIL_SMS = "email_sms"  # the same short message by email and by SMS
    INTERNAL = "internal"  # task for staff, no customer contact
    INTERMEDIARY = "intermediary"  # task to the owning broker / employer contact


CUSTOMER_CHANNELS = (Channel.EMAIL, Channel.SMS, Channel.EMAIL_SMS)


class MessageStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


class Action(StrEnum):
    REMINDER = "reminder"  # upcoming expiry / scheme anniversary
    PAYMENT_REMINDER = "payment_reminder"  # missed or overdue premium
    DOCUMENT_REQUEST = "document_request"
    PLAN_REVIEW = "plan_review"  # scheduled review or milestone conversation
    SERVICE_FOLLOW_UP = "service_follow_up"
    RETENTION_OFFER = "retention_offer"  # renewal discount within the approved cap
    ADD_ON_OFFER = "add_on_offer"  # eligible additional cover (regulated advice)
    REINSTATEMENT = "reinstatement"
    INTERNAL_TASK = "internal_task"


class Trigger(StrEnum):
    """Lifecycle events. Which ones may fire depends on the product's lifecycle type."""

    UPCOMING_EXPIRY = "upcoming_expiry"
    SCHEME_ANNIVERSARY = "scheme_anniversary"
    PAYMENT_OVERDUE = "payment_overdue"
    PREMIUM_MISSED = "premium_missed"
    LAPSE_RISK_SIGNAL = "lapse_risk_signal"
    SCHEDULED_REVIEW = "scheduled_review"
    MILESTONE = "milestone"
    MISSING_DOCUMENT = "missing_document"
