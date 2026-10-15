"""Consent and channel gates for existing customers.

Reminders, document and payment requests are service messages -> need only a consented
channel. Offers are marketing -> also need marketing consent. Broker-owned
  policies get an intermediary task instead of a customer message.
"""

from __future__ import annotations

from typing import Literal

from backend.enums import Channel
from backend.services.rules.facts import RenewalFacts
from backend.services.rules.routing import owns_via_intermediary

Purpose = Literal["marketing", "service"]


def allowed_channels(
    *,
    purpose: Purpose,
    consent_marketing: bool,
    consent_email: bool,
    consent_sms: bool,
    has_email: bool,
    has_phone: bool,
) -> list[Channel]:
    if purpose == "marketing" and not consent_marketing:
        return []
    out: list[Channel] = []
    if consent_email and has_email:
        out.append(Channel.EMAIL)
    if consent_sms and has_phone:
        out.append(Channel.SMS)
    if len(out) == 2:  # both consented: may also reach out on both at once
        out.append(Channel.EMAIL_SMS)
    return out


def renewal_channels(f: RenewalFacts, purpose: Purpose) -> list[Channel]:
    """Allowed channels, the customer's preferred one first."""
    if owns_via_intermediary(f.channel_owner):
        return [Channel.INTERMEDIARY]
    out = allowed_channels(
        purpose=purpose,
        consent_marketing=f.consent_marketing,
        consent_email=f.consent_email,
        consent_sms=f.consent_sms,
        has_email=f.has_email,
        has_phone=f.has_phone,
    )
    return sorted(out, key=lambda c: c != f.preferred_channel)
