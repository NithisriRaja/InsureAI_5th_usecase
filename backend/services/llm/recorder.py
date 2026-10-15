"""Persists every LLM attempt to ``llm_calls`` in its own short transaction.

Audit writes must never break a run: failures are logged and swallowed.
"""

from __future__ import annotations

from typing import Any

from backend.db.models import LLMCall
from backend.db.session import get_db
from backend.utils.ids import new_id
from backend.utils.logging import get_logger

log = get_logger(__name__)


class DbRecorder:
    async def record(self, row: dict[str, Any]) -> str | None:
        call_id = new_id("llm")
        try:
            async with get_db().session() as s:
                s.add(LLMCall(id=call_id, **row))
        except Exception:
            log.exception("llm.audit_write_failed", purpose=row.get("purpose"))
            return None
        return call_id

    async def update(self, call_id: str | None, **fields: Any) -> None:
        if call_id is None:
            return
        try:
            async with get_db().session() as s:
                call = await s.get(LLMCall, call_id)
                if call is not None:
                    for k, v in fields.items():
                        setattr(call, k, v)
        except Exception:
            log.exception("llm.audit_update_failed", call_id=call_id)
