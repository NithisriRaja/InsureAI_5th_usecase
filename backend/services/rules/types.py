"""Rule result types shared by every hard rule.

Rules are pure functions over facts (never ORM objects, never protected attributes).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    BLOCK = "block"  # hard stop: action or channel not allowed
    WARN = "warn"  # informational, shown to the reviewer
    INFO = "info"


class RuleResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    passed: bool
    severity: Severity
    reason: str
    data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def ok(cls, id: str, reason: str, **data: Any) -> RuleResult:
        return cls(id=id, passed=True, severity=Severity.INFO, reason=reason, data=data)

    @classmethod
    def fail(cls, id: str, severity: Severity, reason: str, **data: Any) -> RuleResult:
        return cls(id=id, passed=False, severity=severity, reason=reason, data=data)


def failed(results: list[RuleResult], severity: Severity | None = None) -> list[RuleResult]:
    return [r for r in results if not r.passed and (severity is None or r.severity == severity)]


def dump(results: list[RuleResult]) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in results]
