from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.db.models import Batch, Recommendation, Run
from backend.services import justification


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorBody(BaseModel):
    error: ErrorDetail


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    batch_id: str | None
    use_case: str
    subject_type: str
    subject_id: str
    cycle_key: str
    status: str
    attempts: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    result: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    recommendation_id: str | None = None
    subject_name: str | None = None

    @classmethod
    def of(cls, run: Run) -> RunOut:
        out = cls.model_validate(run)
        out.recommendation_id = (run.result or {}).get("recommendation_id")
        return out


class RunBrief(BaseModel):
    id: str
    status: str
    error_code: str | None = None

    @classmethod
    def of(cls, run: Run | None) -> RunBrief | None:
        return cls(id=run.id, status=run.status, error_code=run.error_code) if run else None


class RecBrief(BaseModel):
    id: str
    status: str
    action: str
    band: str | None
    priority: str
    queue: str
    needs_review: bool
    created_at: datetime
    why: str = ""

    @classmethod
    def of(cls, rec: Recommendation | None) -> RecBrief | None:
        if rec is None:
            return None
        return cls(
            id=rec.id,
            status=rec.status,
            action=rec.action,
            band=rec.band,
            priority=rec.priority,
            queue=rec.queue,
            needs_review=rec.needs_review,
            created_at=rec.created_at,
            why=justification.why(rec),
        )


class BatchOut(BaseModel):
    id: str
    kind: str
    params: dict[str, Any]
    created_at: datetime
    total: int
    counts: dict[str, int]
    done: bool
    skipped: list[dict[str, Any]]
    run_ids: list[str]

    @classmethod
    def of(cls, batch: Batch, counts: dict[str, int], run_ids: list[str]) -> BatchOut:
        total = sum(counts.values())
        active = counts.get("queued", 0) + counts.get("running", 0)
        return cls(
            id=batch.id,
            kind=batch.kind,
            params=batch.params,
            created_at=batch.created_at,
            total=total,
            counts=counts,
            done=active == 0,
            skipped=batch.skipped,
            run_ids=run_ids,
        )
