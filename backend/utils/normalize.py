from __future__ import annotations

import re


def norm_email(email: str | None) -> str | None:
    if not email:
        return None
    email = email.strip().casefold()
    return email or None


def norm_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    return digits or None
