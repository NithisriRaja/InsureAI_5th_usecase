"""Time-ordered, prefixed string ids (e.g. ``run_018f3c...``)."""

from __future__ import annotations

import secrets
import time


def new_id(prefix: str) -> str:
    ms = int(time.time() * 1000)
    return f"{prefix}_{ms:012x}{secrets.token_hex(5)}"


def new_token() -> str:
    """Opaque session token (32 random bytes)."""
    return secrets.token_urlsafe(32)
