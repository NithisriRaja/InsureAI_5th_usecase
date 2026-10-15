"""Fairness guardrail: protected attributes must never reach the LLM or the rules.

Three layers:
1. Facts/feature models simply have no protected fields (checked by unit test).
2. ``redact_text`` scrubs protected terms from free text before use.
3. ``scan_payload`` inspects the exact data payload about to be sent to the LLM and raises
   ``FairnessViolation`` if any protected key or term is still present.

Term matching is a curated word list (POC-grade): deliberately over-redacts rather than leaks.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field

REDACTED = "[REDACTED]"

PROTECTED_KEYS = frozenset(
    {
        "gender",
        "sex",
        "ethnicity",
        "race",
        "religion",
        "faith",
        "marital_status",
        "nationality",
        "citizenship",
        "country_of_birth",
        "disability",
        "sexual_orientation",
        "pregnancy",
        "pregnant",
        "protected",
        "city",
        "postcode",
        "zip",
        "address",
    }
)

_TERMS: dict[str, list[str]] = {
    "religion": [
        "catholic",
        "protestant",
        "christian",
        "muslim",
        "islam",
        "islamic",
        "jewish",
        "judaism",
        "hindu",
        "sikh",
        "buddhist",
        "atheist",
        "practising",
        "practicing",
        "church",
        "mosque",
        "synagogue",
        "temple",
    ],
    "marital_status": [
        "divorced",
        "married",
        "widowed",
        "widow",
        "widower",
        "separated",
        "single mother",
        "single father",
        "single parent",
        "spouse",
        "husband",
        "wife",
    ],
    "gender": [
        "she",
        "her",
        "hers",
        "herself",
        "he",
        "him",
        "his",
        "himself",
        "female",
        "male",
        "woman",
        "man",
        "girl",
        "boy",
        "transgender",
    ],
    "sexual_orientation": ["gay", "lesbian", "bisexual", "homosexual", "heterosexual", "queer"],
    "pregnancy": ["pregnant", "pregnancy", "maternity"],
    "disability": ["disabled", "disability", "wheelchair", "blind", "deaf"],
    "ethnicity": ["black", "hispanic", "latino", "latina", "asian", "caucasian", "ethnic"],
    "nationality": [
        "polish",
        "indian",
        "nigerian",
        "chinese",
        "mexican",
        "pakistani",
        "romanian",
        "irish",
        "british",
        "american",
        "german",
        "french",
        "italian",
        "spanish",
        "filipino",
        "immigrant",
        "refugee",
        "foreigner",
        "citizen",
    ],
}

_PATTERNS: dict[str, re.Pattern[str]] = {
    cat: re.compile(
        r"\b(" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + r")\b",
        re.IGNORECASE,
    )
    for cat, terms in _TERMS.items()
}
# "originally from Poland", "born in Lagos", "moved here from Mexico"
_ORIGIN = re.compile(r"\b(originally from|born in|moved (?:here )?from|native of)\s+[A-Z][\w-]+")


class FairnessReport(BaseModel):
    passed: bool = True
    redactions: int = 0
    categories: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)


class FairnessViolation(Exception):
    def __init__(self, violations: list[str]) -> None:
        super().__init__("protected attribute in LLM payload: " + "; ".join(violations))
        self.violations = violations


def redact_text(text: str | None) -> tuple[str | None, FairnessReport]:
    if not text:
        return text, FairnessReport()
    cats: set[str] = set()
    count = 0

    def sub(cat: str, pattern: re.Pattern[str], s: str) -> str:
        nonlocal count
        new, n = pattern.subn(REDACTED, s)
        if n:
            cats.add(cat)
            count += n
        return new

    out = sub("nationality", _ORIGIN, text)
    for cat, pattern in _PATTERNS.items():
        out = sub(cat, pattern, out)
    return out, FairnessReport(redactions=count, categories=sorted(cats))


def _find_terms(text: str) -> list[str]:
    hits = []
    if _ORIGIN.search(text):
        hits.append("nationality")
    hits.extend(cat for cat, p in _PATTERNS.items() if p.search(text))
    return hits


def scan_payload(payload: Any, path: str = "$") -> list[str]:
    """Return violations found anywhere in a JSON-like payload (keys and string values)."""
    found: list[str] = []
    if isinstance(payload, Mapping):
        for k, v in payload.items():
            key = str(k).casefold()
            if key in PROTECTED_KEYS:
                found.append(f"{path}.{k}: protected key")
            found.extend(scan_payload(v, f"{path}.{k}"))
    elif isinstance(payload, Sequence) and not isinstance(payload, str | bytes):
        for i, v in enumerate(payload):
            found.extend(scan_payload(v, f"{path}[{i}]"))
    elif isinstance(payload, str):
        cleaned = payload.replace(REDACTED, "")
        found.extend(f"{path}: {cat} term" for cat in _find_terms(cleaned))
    return found


def assert_clean(payload: Any) -> None:
    violations = scan_payload(payload)
    if violations:
        raise FairnessViolation(violations)
