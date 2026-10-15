from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.api.deps import db_session, get_runner
from backend.config import get_settings
from backend.db.models import Policy
from backend.db.store import DbSession
from backend.services.llm.client import get_llm_client
from backend.services.llm.types import LLMError
from backend.services.runner import Runner
from backend.utils.clock import today

router = APIRouter(tags=["health"])

MODEL_BY_PROVIDER = {
    "domo": "domo_model",
    "anthropic": "anthropic_model",
}
KEY_BY_PROVIDER = {
    "domo": "domo_api_key",
    "anthropic": "anthropic_api_key",
}


class Ping(BaseModel):
    ok: bool


@router.get("/health")
async def health(
    deep: bool = Query(False, description="Also make one tiny LLM call."),
    s: DbSession = Depends(db_session),
    runner: Runner | None = Depends(get_runner),
) -> dict[str, Any]:
    st = get_settings()
    out: dict[str, Any] = {
        "status": "ok",
        "as_of": today().isoformat(),
        "data": {"location": s.store.location, "policies": len(s.all(Policy))},
        "runner": {"running": runner is not None, "instance": runner.instance if runner else None},
        "llm": {
            "provider": st.llm_provider,
            "model": getattr(st, MODEL_BY_PROVIDER.get(st.llm_provider, ""), None),
            "structured_mode": st.llm_structured_mode,
            "key_configured": bool(getattr(st, KEY_BY_PROVIDER.get(st.llm_provider, ""), "")),
        },
    }
    if deep:
        try:
            await get_llm_client().structured(
                Ping,
                purpose="health_ping",
                instructions="Health check.",
                task='Reply with {"ok": true}.',
                data={},
            )
            out["llm"]["reachable"] = True
        except LLMError as e:
            out["status"] = "degraded"
            out["llm"].update(reachable=False, error=e.code, message=str(e))
    return out
