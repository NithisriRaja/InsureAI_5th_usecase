"""Customer-portal links the workflow agent sends with a message (renewal, payment, ...).

Links are added in code, never written by the LLM, so they are always the approved URL.
"""

from __future__ import annotations

from typing import Any

from backend.config import get_settings
from backend.enums import Action, Channel

LINKS: dict[str, tuple[str, str]] = {
    Action.REMINDER: ("Renew online", "renew"),
    Action.RETENTION_OFFER: ("Renew online", "renew"),
    Action.REINSTATEMENT: ("Restart your cover", "renew"),
    Action.PAYMENT_REMINDER: ("Pay online", "pay"),
    Action.DOCUMENT_REQUEST: ("Upload documents", "documents"),
    Action.PLAN_REVIEW: ("Book your review", "review"),
    Action.ADD_ON_OFFER: ("Talk to us about this cover", "review"),
}


def action_link(action: str, channel: str | None, policy_number: str) -> dict[str, Any] | None:
    """``{"label", "url"}`` for the portal page that completes ``action``; None for internal
    tasks and actions without a self-service page."""
    if channel in (None, Channel.INTERNAL) or action not in LINKS:
        return None
    label, page = LINKS[action]
    base = get_settings().customer_portal_url.rstrip("/")
    return {"label": label, "url": f"{base}/{page}/{policy_number}"}


def with_link(body: str, link: dict[str, Any] | None) -> str:
    return f"{body}\n\n{link['label']}: {link['url']}" if link else body
