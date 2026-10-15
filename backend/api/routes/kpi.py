"""KPI drill-downs: what one dashboard number is made of, who is in it, and what drives it.

``GET /kpi/renewal/{metric}`` answers the question behind a tile ("why 8 high risk?"):
the groups that make up the number, the people in each group with the agent's one-line take,
and the facts or rules that drive it most often. Built from stored recommendations only.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend import rulebook
from backend.api.deps import db_session
from backend.api.errors import AppError
from backend.api.naming import subject_lines, subject_names
from backend.api.routes.dashboard import _due, _latest_recs
from backend.db.models import Policy, Recommendation
from backend.db.store import DbSession
from backend.services import justification, lifecycle

router = APIRouter(prefix="/kpi", tags=["kpi"])

REN_METRICS = ("due", "checked", "lapse", "offers", "pending", "decided")


class Person(BaseModel):
    subject_type: str
    subject_id: str
    name: str
    line: str | None = None
    rec_id: str | None = None
    status: str | None = None
    action: str | None = None
    band: str | None = None
    headline: str = ""
    detail: str = ""


class Group(BaseModel):
    key: str
    label: str
    tone: str = "gray"
    count: int
    blurb: str = ""
    people: list[Person]


class Driver(BaseModel):
    key: str
    label: str
    count: int


class KpiDrill(BaseModel):
    use_case: str
    metric: str
    title: str
    question: str
    answer: str
    total: int
    groups: list[Group]
    drivers_title: str = ""
    drivers: list[Driver] = []


BAND_TONE = {"high": "red", "medium": "amber", "low": "green"}
ACTION_LABEL = {k.value: v for k, v in justification.ACTION_TEXT.items()}
LINE_LABEL = {k: v["label"] for k, v in rulebook.LINES.items()}


def _human(key: str) -> str:
    return key.replace("declared.", "").replace("_", " ")


def _label(key: str) -> str:
    h = _human(key)
    return h[:1].upper() + h[1:]


def _reason(d: dict[str, Any] | None, sig: dict[str, Any]) -> str:
    r = ((d or {}).get("reasons") or [{}])[0]
    if not r.get("signal"):
        return ""
    v = sig.get(r["signal"])
    shown = f" ({v})" if v is not None and not isinstance(v, (dict, list)) else ""
    return f"{_human(r['signal'])}{shown}: {r.get('explanation', '')}"


def _drivers(recs: Iterable[Recommendation], decision: str) -> list[Driver]:
    c: Counter[str] = Counter()
    for r in recs:
        for reason in ((r.decisions or {}).get(decision) or {}).get("reasons") or []:
            if reason.get("signal"):
                c[reason["signal"]] += 1
    return [Driver(key=k, label=_label(k), count=n) for k, n in c.most_common(6)]


class _Ctx:
    def __init__(self, names: dict[str, str], lines: dict[str, str]) -> None:
        self.names, self.lines = names, lines

    def person(self, r: Recommendation, detail: str = "") -> Person:
        return Person(
            subject_type=r.subject_type,
            subject_id=r.subject_id,
            name=self.names.get(r.subject_id, r.subject_id),
            line=self.lines.get(r.subject_id),
            rec_id=r.id,
            status=r.status,
            action=r.action,
            band=r.band,
            headline=justification.headline(r),
            detail=detail,
        )


def _group(
    ctx: _Ctx,
    recs: list[Recommendation],
    key_of: Callable[[Recommendation], str | None],
    order: list[str],
    labels: dict[str, str],
    detail: Callable[[Recommendation], str] = lambda r: "",
    blurbs: dict[str, str] | None = None,
) -> list[Group]:
    buckets: dict[str, list[Recommendation]] = {}
    for r in recs:
        buckets.setdefault(key_of(r) or "none", []).append(r)
    keys = [k for k in order if k in buckets] + sorted(k for k in buckets if k not in order)
    return [
        Group(
            key=k,
            label=labels.get(k, _label(k)),
            tone=BAND_TONE.get(k, "gray"),
            count=len(buckets[k]),
            blurb=(blurbs or {}).get(k, ""),
            people=[ctx.person(r, detail(r)) for r in buckets[k]],
        )
        for k in keys
    ]


def _share(groups: list[Group]) -> str:
    total = sum(g.count for g in groups) or 1
    return ", ".join(
        f"{g.count} {g.label.lower()} ({round(g.count * 100 / total)}%)" for g in groups
    )


async def _renewal(s: DbSession, metric: str, line: str | None, ctx: _Ctx) -> KpiDrill:
    due = await _due(s)
    cycles = {pid: lifecycle.cycle_key(pid, a) for pid, a in due.items()}
    recs = [r for r in await _latest_recs(s, "renewal") if cycles.get(r.subject_id) == r.cycle_key]
    if line:
        recs = [r for r in recs if ctx.lines.get(r.subject_id) == line]
    sig = lambda r: r.signals or {}  # noqa: E731

    if metric == "due":
        policies = {p.id: p for p in s.where(Policy, lambda p: p.id in due)}
        rec_by = {r.subject_id: r for r in recs}
        groups: dict[str, list[Person]] = {}
        for pid, a in due.items():
            p = policies.get(pid)
            if p is None or (line and p.line != line):
                continue
            first = a.triggers[0].type.value if a.triggers else "other"
            r = rec_by.get(pid)
            groups.setdefault(first, []).append(
                Person(
                    subject_type="policy",
                    subject_id=pid,
                    name=ctx.names.get(pid, p.policy_number),
                    line=p.line,
                    rec_id=r.id if r else None,
                    status=r.status if r else "not_checked",
                    action=r.action if r else None,
                    band=r.band if r else None,
                    headline=ctx.person(r).headline if r else "Not checked by the AI yet.",
                    detail=" · ".join(t.detail for t in a.triggers),
                )
            )
        out = sorted(
            (Group(key=k, label=_label(k), count=len(v), people=v) for k, v in groups.items()),
            key=lambda g: -g.count,
        )
        total = sum(g.count for g in out)
        lines = Counter(p.line for p in policies.values() if not line or p.line == line)
        return KpiDrill(
            use_case="renewal",
            metric=metric,
            title="Due for renewal",
            question="Which policies need attention, and what triggered them?",
            answer=f"{total} policies have a live event: {_share(out)}.",
            total=total,
            groups=out,
            drivers_title="By product line",
            drivers=[
                Driver(key=k, label=LINE_LABEL.get(k, _label(k)), count=n)
                for k, n in lines.most_common()
            ],
        )

    if metric == "lapse":
        groups_ = _group(
            ctx,
            recs,
            lambda r: r.band,
            ["high", "medium", "low"],
            {"high": "High risk of leaving", "medium": "Medium risk", "low": "Low risk"},
            detail=lambda r: _reason((r.decisions or {}).get("lapse_risk"), sig(r)),
            blurbs={
                "high": "Cover at risk now: fix payments or make a move this week.",
                "medium": "Wobbly. A nudge or a small offer usually keeps them.",
                "low": "Loyal and settled. A reminder is enough.",
            },
        )
        drivers = _drivers(recs, "lapse_risk")
        top = f" Biggest driver: {drivers[0].label.lower()}." if drivers else ""
        return KpiDrill(
            use_case="renewal",
            metric=metric,
            title="Risk of not renewing",
            question="Who might walk, and what's pushing them?",
            answer=f"{len(recs)} policies rated: {_share(groups_)}.{top}",
            total=len(recs),
            groups=groups_,
            drivers_title="Facts behind the risk calls",
            drivers=drivers,
        )

    if metric == "offers":
        offers = [r for r in recs if r.action == "retention_offer" and r.offer]

        def money(x: Any) -> str:
            return f"{(x or 0) / 100:,.0f}"

        groups_ = _group(
            ctx,
            offers,
            lambda r: f"{float((r.offer or {}).get('discount_pct') or 0):g}% off",
            [],
            {},
            detail=lambda r: (
                f"{money((r.offer or {}).get('premium_before'))} → "
                f"{money((r.offer or {}).get('premium_after'))} a year "
                f"(cap {(r.offer or {}).get('max_discount_pct')}%)"
            ),
        )
        return KpiDrill(
            use_case="renewal",
            metric=metric,
            title="Personalised offers",
            question="Who gets a discount, how much, and why them?",
            answer=f"{len(offers)} retention offers, always within each customer's cap."
            if offers
            else "No discounts suggested. The agent prefers fixing the problem to paying for it.",
            total=len(offers),
            groups=groups_,
            drivers_title="Facts behind the offers",
            drivers=_drivers(offers, "lapse_risk"),
        )

    if metric == "pending":
        recs = [r for r in recs if r.status == "pending_approval"]
    elif metric == "decided":
        recs = [r for r in recs if r.status in ("approved", "approved_with_edits", "rejected")]
    groups_ = _group(
        ctx,
        recs,
        (lambda r: r.status) if metric == "decided" else (lambda r: r.action),
        ["approved", "approved_with_edits", "rejected"] if metric == "decided" else [],
        ACTION_LABEL | {"approved_with_edits": "Approved with changes"},
    )
    groups_.sort(key=lambda g: -g.count)
    title = {"pending": "Awaiting decision", "decided": "Decided"}.get(metric, "Checked by AI")
    return KpiDrill(
        use_case="renewal",
        metric=metric,
        title=title,
        question="What next step did the agent pick for each policy?",
        answer=f"{len(recs)} policies: {_share(groups_)}." if recs else "Nothing here yet.",
        total=len(recs),
        groups=groups_,
        drivers_title="Facts behind the calls",
        drivers=_drivers(recs, "lapse_risk"),
    )


@router.get("/renewal/{metric}", response_model=KpiDrill)
async def drill(
    metric: str,
    line: str | None = Query(None, description="Product line"),
    s: DbSession = Depends(db_session),
) -> KpiDrill:
    if metric not in REN_METRICS:
        raise AppError(422, "validation_error", f"metric must be one of {list(REN_METRICS)}")
    subjects = [("policy", p.id) for p in s.all(Policy)]
    ctx = _Ctx(names=await subject_names(s, subjects), lines=await subject_lines(s, subjects))
    return await _renewal(s, metric, line, ctx)
