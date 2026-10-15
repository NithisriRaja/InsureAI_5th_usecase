from __future__ import annotations

import json
from typing import Any, Literal

import httpx
import pytest
import respx
from pydantic import BaseModel, Field

from backend.agents.personalisation.decision import DraftMessage, check_draft, render
from backend.agents.shared.decision import Reason, grounding_errors
from backend.db.models import LLMCall
from backend.services.llm.client import LLMClient
from backend.services.llm.jsonutil import extract_json, strict_schema
from backend.services.llm.providers.anthropic_provider import AnthropicProvider
from backend.services.llm.providers.domo import DomoProvider
from backend.services.llm.providers.fake import FakeProvider
from backend.services.llm.ratelimit import RateLimiter
from backend.services.llm.recorder import DbRecorder
from backend.services.llm.retry import RetryPolicy, parse_retry_after
from backend.services.llm.types import (
    ChatMessage,
    LLMInvalidOutput,
    LLMRefusal,
    LLMUnavailable,
    ProviderError,
)
from backend.services.rules.fairness import FairnessViolation
from backend.utils.context import node_context, run_context

URL = "https://domo.test/api/ai/v1/text/generation"


class Verdict(BaseModel):
    band: Literal["high", "medium", "low"]
    score: float = Field(ge=0, le=1)
    reasons: list[Reason] = Field(min_length=1)


SIGNALS = {"pages_viewed": 12, "requested_callback": True}
GOOD = {"band": "high", "score": 0.8, "reasons": [{"signal": "pages_viewed", "explanation": "x"}]}


class MemRecorder:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def record(self, row: dict[str, Any]) -> str:
        cid = f"c{len(self.rows)}"
        self.rows[cid] = dict(row)
        return cid

    async def update(self, call_id: str | None, **fields: Any) -> None:
        if call_id:
            self.rows[call_id].update(fields)

    def statuses(self) -> list[str]:
        return [r["status"] for r in self.rows.values()]


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, s: float) -> None:
        self.calls.append(s)


def make_client(provider=None, *, max_attempts=4, budget=60.0, recorder=None, sleeps=None):
    provider = provider or DomoProvider(
        base_url="https://domo.test/api", api_key="k", model="m", mode="prompt", timeout_s=5
    )
    return LLMClient(
        provider,
        mode=provider.mode if hasattr(provider, "mode") else "prompt",
        limiter=RateLimiter(0, 2),
        retry=RetryPolicy(
            max_attempts=max_attempts,
            max_total_wait_s=budget,
            base_s=0.01,
            cap_s=0.05,
            sleep=sleeps or Sleeps(),
        ),
        recorder=recorder or MemRecorder(),
    )


def ok(content: Any) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(
        200,
        json={
            "modelId": "m",
            "choices": [{"output": text, "recoveryDetail": None}],
            "output": text,
            "modelProviderUsage": {"inputTokens": 5, "outputTokens": 7},
        },
    )


async def ask(client: LLMClient, validate=None) -> Verdict:
    return await client.structured(
        Verdict,
        purpose="lapse_risk",
        instructions="Classify.",
        task="Go.",
        data={"signals": SIGNALS},
        validate=validate or (lambda v: grounding_errors(v.reasons, SIGNALS)),
    )


# ------------------------------------------------------------ retries ---


@respx.mock
async def test_429_with_retry_after_then_success() -> None:
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}, json={"error": "slow down"}),
            ok(GOOD),
        ]
    )
    sleeps, rec = Sleeps(), MemRecorder()
    v = await ask(make_client(sleeps=sleeps, recorder=rec))
    assert v.band == "high"
    assert route.call_count == 2
    assert sleeps.calls == [2.0]  # honoured Retry-After exactly
    assert rec.statuses() == ["error", "ok"]


@respx.mock
async def test_5xx_exhausts_attempts() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(503, text="down"))
    with pytest.raises(LLMUnavailable) as ei:
        await ask(make_client(max_attempts=3))
    assert route.call_count == 3
    assert ei.value.detail["status"] == 503


@respx.mock
@pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
async def test_client_errors_fail_fast(status: int) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(status, text="nope"))
    with pytest.raises(LLMUnavailable):
        await ask(make_client())
    assert route.call_count == 1


@respx.mock
async def test_retry_after_beyond_budget_gives_up_without_sleeping() -> None:
    respx.post(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "3600"}))
    sleeps = Sleeps()
    with pytest.raises(LLMUnavailable) as ei:
        await ask(make_client(sleeps=sleeps, budget=60))
    assert sleeps.calls == []
    assert ei.value.detail["code"] == "rate_limited"


@respx.mock
async def test_timeout_and_network_errors_retry() -> None:
    respx.post(URL).mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.ConnectError("boom"), ok(GOOD)]
    )
    assert (await ask(make_client())).band == "high"


@respx.mock
async def test_200_without_output_is_retried() -> None:
    respx.post(URL).mock(
        side_effect=[httpx.Response(200, json={"choices": [], "output": None}), ok(GOOD)]
    )
    assert (await ask(make_client())).band == "high"


@respx.mock
async def test_empty_completion_is_retried() -> None:
    respx.post(URL).mock(side_effect=[ok(""), ok(GOOD)])
    assert (await ask(make_client())).band == "high"


# ---------------------------------------------------- output handling ---


@respx.mock
async def test_invalid_then_repaired() -> None:
    bad = {"band": "scorching", "score": 3, "reasons": []}
    route = respx.post(URL).mock(side_effect=[ok(bad), ok(GOOD)])
    rec = MemRecorder()
    assert (await ask(make_client(recorder=rec))).band == "high"
    repair_input = json.loads(route.calls[1].request.content)["input"]
    assert "### YOUR PREVIOUS REPLY" in repair_input and "scorching" in repair_input
    assert repair_input.rstrip().endswith("Return the corrected JSON object only.")
    assert rec.statuses() == ["invalid", "ok"]


@respx.mock
async def test_invalid_twice_fails() -> None:
    respx.post(URL).mock(return_value=ok("I think this customer is high risk!"))
    with pytest.raises(LLMInvalidOutput):
        await ask(make_client())


@respx.mock
async def test_ungrounded_reason_triggers_repair() -> None:
    ungrounded = {**GOOD, "reasons": [{"signal": "zodiac_sign", "explanation": "x"}]}
    route = respx.post(URL).mock(side_effect=[ok(ungrounded), ok(GOOD)])
    await ask(make_client())
    assert "zodiac_sign" in json.loads(route.calls[1].request.content)["input"]


@respx.mock
async def test_fenced_json_with_think_tags_is_parsed() -> None:
    text = "<think>hmm {not json}</think>\nSure:\n```json\n" + json.dumps(GOOD) + "\n```"
    respx.post(URL).mock(return_value=ok(text))
    assert (await ask(make_client())).score == 0.8


@respx.mock
async def test_prompt_contains_schema_security_note_and_delimited_data() -> None:
    route = respx.post(URL).mock(return_value=ok(GOOD))
    await ask(make_client())
    body = json.loads(route.calls[0].request.content)
    system, user = body["system"], body["input"]
    assert system.startswith("PURPOSE: lapse_risk")
    assert "untrusted" in system and '"band"' in system
    assert "<data>" in user and "</data>" in user
    assert body["model"] == "m"
    assert route.calls[0].request.headers["X-DOMO-Developer-Token"] == "k"


# ------------------------------------------------------------ fairness ---


@respx.mock
async def test_fairness_violation_blocks_before_any_http_call() -> None:
    route = respx.post(URL).mock(return_value=ok(GOOD))
    rec = MemRecorder()
    client = make_client(recorder=rec)
    with pytest.raises(FairnessViolation):
        await client.structured(
            Verdict,
            purpose="lapse_risk",
            instructions="x",
            task="x",
            data={"signals": {"gender": "female"}},
        )
    assert route.call_count == 0
    assert rec.statuses() == ["blocked"]
    assert list(rec.rows.values())[0]["request"] == {}


# ------------------------------------------------------- provider shapes ---


def test_domo_single_turn_body() -> None:
    p = DomoProvider(base_url="https://x/api/", api_key="k", model="m", mode="prompt", timeout_s=5)
    body = p.build_body([ChatMessage("system", "sys"), ChatMessage("user", "hi")])
    assert body == {"input": "hi", "system": "sys", "model": "m"}
    assert p._url == "https://x/api/ai/v1/text/generation"


def test_anthropic_kwargs() -> None:
    p = AnthropicProvider(
        api_key="k",
        model="claude-opus-5-5",
        mode="json_schema",
        timeout_s=5,
        effort="low",
        client=object(),
    )
    kw = p.build_kwargs(
        [ChatMessage("system", "sys"), ChatMessage("user", "u")],
        schema={"type": "object"},
        max_tokens=100,
    )
    assert kw["system"] == "sys"
    assert kw["messages"] == [{"role": "user", "content": "u"}]
    assert kw["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": {"type": "object"}},
    }
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert "temperature" not in kw


def test_anthropic_no_fallback_on_unsupported_model() -> None:
    p = AnthropicProvider(
        api_key="k", model="claude-haiku-5-5", mode="prompt", timeout_s=5, client=object()
    )
    kw = p.build_kwargs([ChatMessage("user", "u")], schema={"type": "object"}, max_tokens=10)
    assert "fallbacks" not in kw and "betas" not in kw
    assert "format" not in kw.get("output_config", {})


class _Block:
    def __init__(self, type_: str, text: str = "") -> None:
        self.type, self.text = type_, text


class _Resp:
    def __init__(self, stop_reason: str, blocks: list[_Block]) -> None:
        self.stop_reason, self.content, self.model = stop_reason, blocks, "claude-opus-5-5"
        self.usage = None
        self.stop_details = None


class _StubAnthropic:
    def __init__(self, resp: _Resp) -> None:
        async def create(**_: Any) -> _Resp:
            return resp

        self.beta = type("B", (), {"messages": type("M", (), {"create": staticmethod(create)})})


async def test_anthropic_refusal_maps_to_llm_refusal() -> None:
    p = AnthropicProvider(
        api_key="k",
        model="claude-opus-5-5",
        mode="json_schema",
        timeout_s=5,
        client=_StubAnthropic(_Resp("refusal", [])),
    )
    with pytest.raises(LLMRefusal):
        await ask(make_client(p))


async def test_anthropic_text_blocks_parsed_skipping_thinking() -> None:
    resp = _Resp("end_turn", [_Block("thinking"), _Block("text", json.dumps(GOOD))])
    p = AnthropicProvider(
        api_key="k",
        model="claude-opus-5-5",
        mode="json_schema",
        timeout_s=5,
        client=_StubAnthropic(resp),
    )
    assert (await ask(make_client(p))).band == "high"


# --------------------------------------------------------------- utils ---


def test_strict_schema_inlines_and_locks() -> None:
    s = strict_schema(Verdict)
    assert "$defs" not in json.dumps(s) and "$ref" not in json.dumps(s)
    assert s["additionalProperties"] is False and set(s["required"]) == {"band", "score", "reasons"}
    item = s["properties"]["reasons"]["items"]
    assert item["additionalProperties"] is False
    assert "minimum" not in json.dumps(s)


def test_extract_json_failures() -> None:
    with pytest.raises(ValueError):
        extract_json("no json here")
    assert extract_json('prefix {"a": "}"} suffix') == {"a": "}"}


def test_parse_retry_after_variants() -> None:
    assert parse_retry_after({"retry-after": "7"}) == 7.0
    assert parse_retry_after({}) is None
    assert parse_retry_after({"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"}) == 0.0


async def test_rate_limiter_spaces_requests() -> None:
    now = [100.0]
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    lim = RateLimiter(rpm=30, max_concurrency=5, clock=lambda: now[0], sleep=fake_sleep)
    for _ in range(3):
        async with lim.slot():
            pass
    assert sleeps == [2.0, 4.0]  # 30 rpm -> one start every 2s


async def test_retry_policy_non_provider_errors_propagate() -> None:
    async def boom(_: int) -> None:
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        await RetryPolicy(sleep=Sleeps()).run(boom)


async def test_fake_provider_errors_propagate() -> None:
    def responder(purpose: str, _: list[ChatMessage]) -> Any:
        raise ProviderError("nope", retryable=False, code="x")

    with pytest.raises(LLMUnavailable):
        await ask(make_client(FakeProvider(responder)))


# ------------------------------------------------------------- drafts ---


@pytest.mark.parametrize(
    ("subject", "body", "channel", "errs"),
    [
        ("Renewal", "Hi {first_name}, renew with 10% off.", "email", 0),
        ("Renewal", "Hi {first_name}, renew with 15% off.", "email", 1),
        (None, "Hi {first_name}, renew soon.", "email", 1),
        ("Subj", "Hi {first_name}", "sms", 1),
        (None, "Hi {customer_name}, renew.", "sms", 1),
        (None, "x" * 400, "sms", 1),
        (None, "Hi [REDACTED]", "sms", 1),
    ],
)
def test_check_draft(subject, body, channel, errs) -> None:
    d = DraftMessage(subject=subject, body=body)
    assert len(check_draft(d, channel=channel, allowed_percents={10.0})) == errs


def test_check_draft_product_name_is_not_a_discount() -> None:
    d = DraftMessage(subject=None, body="Hi {first_name}, your Regular Savings Plan has lapsed.")
    kw: dict = {"channel": "sms", "allowed_percents": set(), "allowed_amounts": set()}
    assert check_draft(d, **kw, discount_offered=False)  # "Savings" alone looks like an offer
    assert not check_draft(d, **kw, discount_offered=False, known_names=("Regular Savings Plan",))
    generic = DraftMessage(subject=None, body="Hi {first_name}, let's review your savings needs.")
    assert not check_draft(generic, **kw, discount_offered=False, known_names=("Savings",))
    offer = DraftMessage(subject=None, body="Hi {first_name}, get a discount on renewal.")
    assert check_draft(offer, **kw, discount_offered=False, known_names=("Savings",))


def test_render_fills_name() -> None:
    assert render("Hi {first_name}!", "Ava") == "Hi Ava!"
    assert render("Hi {first_name}!", None) == "Hi there!"


# ------------------------------------------------------ db recorder + ctx ---


@respx.mock
async def test_db_recorder_persists_attempts_with_run_and_node(db) -> None:
    respx.post(URL).mock(side_effect=[httpx.Response(500), ok(GOOD)])
    client = make_client(recorder=DbRecorder())
    with run_context("run_abc"), node_context("scoring"):
        await ask(client)
    async with db.session() as s:

        rows = sorted(s.all(LLMCall), key=lambda c: c.attempt)
    assert [(r.attempt, r.status, r.run_id, r.node) for r in rows] == [
        (1, "error", "run_abc", "scoring"),
        (2, "ok", "run_abc", "scoring"),
    ]
    assert rows[1].parsed == GOOD and rows[1].prompt_tokens == 5


def test_check_draft_email_sms_needs_subject_and_sms_length() -> None:
    ok = DraftMessage(subject="Renewal", body="Hi {first_name}, your renewal is due soon.")
    assert not check_draft(ok, channel="email_sms", allowed_percents=set())
    assert check_draft(
        DraftMessage(subject=None, body=ok.body), channel="email_sms", allowed_percents=set()
    )
    long = DraftMessage(subject="Renewal", body="x" * 400)
    assert check_draft(long, channel="email_sms", allowed_percents=set())
