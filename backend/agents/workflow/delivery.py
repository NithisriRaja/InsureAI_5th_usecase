"""Workflow agent, delivery step: sends approved messages and tasks (mock gateway).

Messages are written as ``queued`` in the same transaction as the approval, then sent here.
Each message is claimed with a check-then-set (queued -> sending, no ``await`` in between) so
it is sent once even with several senders; the provider call is idempotent on the message id.
"""

from __future__ import annotations

from backend.db.models import Message
from backend.db.repositories import audit as audit_repo
from backend.db.session import Database
from backend.integrations.base import CRM
from backend.utils.clock import utcnow
from backend.utils.logging import get_logger

log = get_logger(__name__)
MAX_SEND_ATTEMPTS = 3


class MockMessaging:
    """Pretend gateway. Fails deterministically when there is no recipient."""

    def __init__(self) -> None:
        self.sent: dict[str, str] = {}  # idempotency key -> provider ref

    async def send(
        self,
        *,
        channel: str,
        recipient: str | None,
        body: str,
        subject: str | None,
        idempotency_key: str,
    ) -> str:
        if idempotency_key in self.sent:
            return self.sent[idempotency_key]
        if not recipient:
            raise RuntimeError(f"no {channel} recipient on file")
        ref = f"mock-{channel}-{idempotency_key[-8:]}"
        self.sent[idempotency_key] = ref
        return ref


async def deliver_pending(
    db: Database, gateway: MockMessaging, crm: CRM | None = None, limit: int = 20
) -> int:
    """Send queued messages; each delivered one is logged on the customer's CRM record."""
    async with db.session() as s:
        queued = s.where(Message, lambda m: m.status == "queued")
        queued.sort(key=lambda m: m.created_at)
        ids = [m.id for m in queued[:limit]]
    sent = 0
    for mid in ids:
        async with db.session() as s:
            msg = await s.get(Message, mid)
            if msg is None or msg.status != "queued":
                continue
            msg.status = "sending"
            msg.attempts += 1
        try:
            ref = await gateway.send(
                channel=msg.channel,
                recipient=msg.recipient,
                body=msg.body,
                subject=None,
                idempotency_key=msg.id,
            )
            status, error = "delivered", None
        except Exception as e:  # noqa: BLE001
            ref, error = None, str(e)
            status = (
                "failed" if msg.attempts >= MAX_SEND_ATTEMPTS or not msg.recipient else "queued"
            )
        async with db.session() as s:
            msg.status = status
            msg.provider_ref = ref
            msg.error = error
            msg.sent_at = utcnow() if status == "delivered" else None
            audit_repo.add_event(
                s,
                event_type=f"message.{status}",
                recommendation_id=msg.recommendation_id,
                subject_type=msg.subject_type,
                subject_id=msg.subject_id,
                payload={
                    "message_id": mid,
                    "channel": msg.channel,
                    "provider_ref": ref,
                    "error": error,
                },
            )
        if status == "delivered" and crm is not None:
            await crm.log_activity(
                kind="message_delivered",
                policy_id=msg.subject_id if msg.subject_type == "policy" else None,
                recommendation_id=msg.recommendation_id,
                channel=msg.channel,
                summary=msg.body.splitlines()[0][:200],
            )
        sent += status == "delivered"
        log.info("message.processed", message_id=mid, status=status)
    return sent
