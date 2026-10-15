"""Human-in-the-loop decisions: approve / reject / edit (= approve with changes).

Order of checks: exists -> role -> still pending -> version -> expiry -> staleness (re-run hard
rules on *current* data) -> edit validation -> atomic conditional write. The final write
re-checks ``status == pending_approval and version == expected`` with no ``await`` in between
(see ``backend.db.store``), so only the first decision wins even if two reviewers pass every
earlier check at the same time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.agents.personalisation.decision import DraftMessage, check_draft
from backend.agents.workflow.links import action_link, with_link
from backend.api.session_auth import Actor
from backend.db.models import Approval, Customer, Message, Recommendation, User
from backend.db.repositories import audit as audit_repo
from backend.db.repositories import policies as policies_repo
from backend.db.session import Database, IntegrityError
from backend.enums import Action, Channel, Decision, RecStatus
from backend.integrations import crm_for
from backend.services import lifecycle
from backend.services.rules import renewal as renewal_rules
from backend.services.rules.routing import approver_roles
from backend.utils.clock import utcnow
from backend.utils.ids import new_id

EDITABLE_FIELDS = {
    "action",
    "channel",
    "discount_pct",
    "add_on_code",
    "draft_message",
    "draft_subject",
}


class DecisionError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


@dataclass
class DecisionResult:
    recommendation: Recommendation
    approval: Approval
    message: Message | None = None
    violations: list[str] = field(default_factory=list)


async def _current_renewal_assessment(db: Database, policy_id: str):
    async with db.session() as s:
        policy = await policies_repo.get(s, policy_id)
        if policy is None:
            return None, None
        a = await lifecycle.assess_policy(s, policy)
    return policy, a


async def _stale_reason(db: Database, rec: Recommendation) -> str | None:
    """Re-check the hard rules against today's data. Returns a reason if the rec is stale."""
    policy, a = await _current_renewal_assessment(db, rec.subject_id)
    if policy is None or a is None:
        return "policy no longer exists"
    if a.state == renewal_rules.RenewalState.SKIP:
        return f"policy is now {a.skip_reason}"
    if lifecycle.cycle_key(policy.id, a) != rec.cycle_key:
        return "the lifecycle event changed since the recommendation"
    if rec.action not in a.allowed_actions:
        return (
            f"action '{rec.action}' no longer allowed (now {[x.value for x in a.allowed_actions]})"
        )
    return None


async def _validate_edits(db: Database, rec: Recommendation, edits: dict[str, Any]) -> dict:
    unknown = set(edits) - EDITABLE_FIELDS
    if unknown:
        raise DecisionError(
            422,
            "rule_violation",
            f"Fields not editable: {sorted(unknown)}",
            [{"rule": "edit.field_not_editable", "fields": sorted(unknown)}],
        )
    if not edits:
        raise DecisionError(422, "rule_violation", "Edit needs at least one changed field.")
    changes: dict[str, Any] = {}
    violations: list[dict[str, str]] = []

    policy, a = await _current_renewal_assessment(db, rec.subject_id)
    action = edits.get("action", rec.action)
    channel = edits.get("channel", rec.channel)
    old_offer = rec.offer or {}
    discount = edits.get(
        "discount_pct",
        old_offer.get("discount_pct") if action == Action.RETENTION_OFFER else None,
    )
    add_on = edits.get(
        "add_on_code", old_offer.get("code") if action == Action.ADD_ON_OFFER else None
    )
    if action == Action.ADD_ON_OFFER and not add_on:
        violations.append({"rule": "suitability.add_on", "reason": "Add-on code required."})
    for r in renewal_rules.validate_intervention(
        a, action=action, channel=channel, discount_pct=discount, add_on_code=add_on
    ):
        violations.append({"rule": r.id, "reason": r.reason})
    body = edits.get("draft_message", rec.draft_message)
    subject = edits.get("draft_subject", rec.draft_subject)
    if action == Action.INTERNAL_TASK or channel == Channel.INTERNAL:
        body, subject = None, None
    elif not body:
        violations.append({"rule": "draft.missing", "reason": "Customer message required."})
    else:
        allowed = {float(discount)} if discount else set()
        if "premium_change_pct" in a.signals:
            allowed.add(float(a.signals["premium_change_pct"]))
        for err in check_draft(
            DraftMessage(subject=subject, body=body),
            channel=channel,
            allowed_percents=allowed,
            forbid_monthly=a.signals.get("payment_frequency") != "monthly",
            discount_offered=bool(discount),
        ):
            violations.append({"rule": "draft.check", "reason": err})
    changes.update(action=action, channel=channel, draft_message=body, draft_subject=subject)
    changes["link"] = action_link(action, channel, policy.policy_number) if body else None
    if action == Action.RETENTION_OFFER and discount:
        premium = old_offer.get("premium_before") or round(
            (rec.signals.get("premium") or 0) * 100
        )  # signals hold major units
        changes["offer"] = {
            **old_offer,
            "type": "discount",
            "discount_pct": discount,
            "max_discount_pct": a.max_discount_pct,
            "premium_before": premium,
            "premium_after": round(premium * (100 - discount) / 100),
        }
    elif action == Action.ADD_ON_OFFER and add_on:
        changes["offer"] = {"type": "add_on", "code": add_on}
    else:
        changes["offer"] = None
    if violations:
        raise DecisionError(422, "rule_violation", "Edit breaks business rules.", violations)
    return changes


def _still_open(rec: Recommendation, version: int) -> bool:
    return rec.status == RecStatus.PENDING_APPROVAL and rec.version == version


def _snapshot(rec: Recommendation) -> dict[str, Any]:
    keys = (
        "action",
        "channel",
        "offer",
        "draft_subject",
        "draft_message",
        "priority",
        "queue",
        "band",
        "confidence",
        "explanation",
        "version",
    )
    return {k: getattr(rec, k) for k in keys}


async def decide(
    db: Database,
    rec_id: str,
    actor: Actor,
    decision: Decision,
    *,
    expected_version: int | None,
    reason: str | None,
    edits: dict[str, Any] | None = None,
) -> DecisionResult:
    async with db.session() as s:
        rec = await s.get(Recommendation, rec_id)
        if rec is None:
            raise DecisionError(404, "not_found", f"recommendation {rec_id} not found")
        if actor.role not in approver_roles(rec.queue):
            raise DecisionError(
                403, "forbidden", f"Role '{actor.role}' cannot decide the {rec.queue} queue."
            )
        if rec.status != RecStatus.PENDING_APPROVAL:
            who = await s.get(User, rec.decided_by) if rec.decided_by else None
            raise DecisionError(
                409,
                "conflict",
                f"Already {rec.status}.",
                {
                    "status": rec.status,
                    "decided_by": who.name if who else None,
                    "decided_at": rec.decided_at.isoformat() if rec.decided_at else None,
                },
            )
        if expected_version is not None and expected_version != rec.version:
            raise DecisionError(
                409,
                "conflict",
                "Recommendation changed; reload it.",
                {"current_version": rec.version},
            )
        version = rec.version

    if decision == Decision.REJECTED and not (reason or "").strip():
        raise DecisionError(422, "rule_violation", "A reason is required to reject.")

    if rec.expires_at and rec.expires_at < utcnow():
        await _close(db, rec, version, RecStatus.EXPIRED, "expired")
        raise DecisionError(409, "expired", "Recommendation expired; re-run to get a fresh one.")

    if decision != Decision.REJECTED:
        stale = await _stale_reason(db, rec)
        if stale:
            await _close(db, rec, version, RecStatus.SUPERSEDED, stale)
            raise DecisionError(409, "stale", f"Recommendation is stale: {stale}.")

    changes = (
        await _validate_edits(db, rec, edits or {})
        if decision == Decision.APPROVED_WITH_EDITS
        else {}
    )
    now = utcnow()

    async with db.session() as s:
        fresh = await s.get(Recommendation, rec.id)
        if fresh is None or not _still_open(fresh, version):
            raise DecisionError(409, "conflict", "Someone else decided this first; reload it.")
        original = _snapshot(fresh)
        for key, value in {
            "status": decision.value,
            "version": version + 1,
            "decided_at": now,
            "decided_by": actor.user_id,
            **changes,
        }.items():
            setattr(fresh, key, value)
        approval = Approval(
            id=new_id("apv"),
            recommendation_id=rec.id,
            decision=decision.value,
            user_id=actor.user_id,
            actor_name=actor.name,
            actor_role=actor.role,
            session_id=actor.session_id,
            reason=reason,
            edits=edits or {},
            original_snapshot=original,
            created_at=now,
        )
        try:
            s.add(approval)
        except IntegrityError as e:  # one approval per recommendation: backstop
            raise DecisionError(409, "conflict", "Already decided.") from e
        message = None
        if (
            decision != Decision.REJECTED
            and fresh.channel
            in (Channel.EMAIL, Channel.SMS, Channel.EMAIL_SMS, Channel.INTERMEDIARY)
            and fresh.draft_message
        ):
            message = await _outbox(s, fresh)
        audit_repo.add_event(
            s,
            event_type=f"recommendation.{decision.value}",
            run_id=fresh.run_id,
            recommendation_id=fresh.id,
            subject_type=fresh.subject_type,
            subject_id=fresh.subject_id,
            actor=f"{actor.name} ({actor.role})",
            payload={
                "reason": reason,
                "edits": edits or {},
                "message_id": message.id if message else None,
            },
        )
    await crm_for(db).log_activity(
        kind="follow_up_rejected" if decision == Decision.REJECTED else "follow_up_approved",
        policy_id=fresh.subject_id,
        recommendation_id=fresh.id,
        channel=fresh.channel,
        summary=f"{_act_label(fresh.action)} {decision.value.replace('_', ' ')}"
        + (f": {reason}" if reason else ""),
        actor=f"{actor.name} ({actor.role})",
    )
    return DecisionResult(recommendation=fresh, approval=approval, message=message)


def _act_label(action: str) -> str:
    return action.replace("_", " ").capitalize()


async def _outbox(s: Any, rec: Recommendation) -> Message:
    recipient = None
    if rec.subject_type == "policy":
        policy = await policies_repo.get(s, rec.subject_id)
        customer = await s.get(Customer, policy.customer_id) if policy else None
        if rec.channel == Channel.INTERMEDIARY:
            recipient = policy.intermediary if policy else None
        elif customer:
            recipient = {
                Channel.EMAIL: customer.email,
                Channel.SMS: customer.phone,
                # Both: one outbox row, delivered to each address on file.
                Channel.EMAIL_SMS: ", ".join(filter(None, [customer.email, customer.phone])),
            }.get(Channel(rec.channel)) or None
    body = with_link(rec.draft_message or "", rec.link)
    if rec.draft_subject:
        body = f"Subject: {rec.draft_subject}\n\n{body}"
    msg = Message(
        id=new_id("msg"),
        recommendation_id=rec.id,
        subject_type=rec.subject_type,
        subject_id=rec.subject_id,
        channel=rec.channel,
        recipient=recipient,
        body=body,
        status="queued",
    )
    s.add(msg)
    return msg


async def _close(
    db: Database, rec: Recommendation, version: int, status: RecStatus, reason: str
) -> None:
    async with db.session() as s:
        current = await s.get(Recommendation, rec.id)
        if current is not None and _still_open(current, version):
            current.status = status.value
            current.version = version + 1
            audit_repo.add_event(
                s,
                event_type=f"recommendation.{status.value}",
                recommendation_id=rec.id,
                subject_type=rec.subject_type,
                subject_id=rec.subject_id,
                payload={"reason": reason},
            )
