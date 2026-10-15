"""Approval routing (who owns the customer, who approves).

- Queues come from the approval matrix, then shift to the adviser queue for adviser-owned
  relationships (except pure service-team work such as payment reminders).
"""

from __future__ import annotations

from backend import rulebook
from backend.enums import ChannelOwner, Queue, Role

QUEUE_ROLES: dict[str, set[Role]] = {
    Queue.ADVISER: {Role.ADVISER, Role.ADMIN},
    Queue.RETENTION: {Role.RETENTION, Role.ADMIN},
}


def route_queue(action: str, channel_owner: str | None, *, regulated_product: bool) -> Queue:
    entry = rulebook.APPROVAL_MATRIX.get(action)
    if entry is None:
        raise KeyError(f"action {action!r} is not in the approval matrix")
    queue = Queue(entry["queue"])
    adviser_owned = channel_owner == ChannelOwner.ADVISER
    if (
        queue == Queue.RETENTION
        and adviser_owned
        and action not in rulebook.SERVICE_TEAM_ACTIONS
    ):
        return Queue.ADVISER
    if queue == Queue.ADVISER and not adviser_owned and not regulated_product:
        return Queue.RETENTION
    return queue


def approver_roles(queue: str) -> set[Role]:
    return QUEUE_ROLES.get(queue, {Role.ADMIN})


def owns_via_intermediary(channel_owner: str | None) -> bool:
    """Broker / employer owns the relationship: contact goes to them, not the customer."""
    return (
        channel_owner in (ChannelOwner.BROKER, ChannelOwner.EMPLOYER)
        and not rulebook.BROKER_DIRECT_CONTACT_ALLOWED
    )
