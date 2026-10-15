"""Read models for the InsureAI web UI: renewals dashboard, renewal management, retention,
extra cover, workflow, and the per-customer "how the agents decided" trace.

Everything is computed from the stored data and the lifecycle rules on each request; nothing
here changes data. Money is in minor units, like the rest of the API.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend import rulebook
from backend.api.deps import db_session, get_database, get_runner
from backend.api.errors import not_found
from backend.api.schemas.common import BatchOut
from backend.api.session_auth import optional_actor
from backend.db.models import (
    AuditEvent,
    Batch,
    CrmActivity,
    Customer,
    LLMCall,
    Message,
    Payment,
    Policy,
    Product,
    Recommendation,
)
from backend.db.session import Database
from backend.db.store import DbSession
from backend.enums import EXPIRY_LIFECYCLES, PolicyStatus, RecStatus
from backend.services import intake, justification, lifecycle
from backend.services.rules.renewal import RenewalAssessment, RenewalState
from backend.services.runner import Runner
from backend.utils.clock import today
from backend.utils.ids import new_id

router = APIRouter(prefix="/overview", tags=["overview"])

Health = Literal["on_track", "due_soon", "at_risk", "overdue", "lapsed", "renewed", "cancelled"]
HEALTH_LABEL = {
    "on_track": "On Track",
    "due_soon": "Due Soon",
    "at_risk": "At Risk",
    "overdue": "Overdue",
    "lapsed": "Lapsed",
    "renewed": "Renewed",
    "cancelled": "Cancelled",
}
_HISTORIC = (RecStatus.SUPERSEDED, RecStatus.EXPIRED)
_DECIDED = (RecStatus.APPROVED, RecStatus.APPROVED_WITH_EDITS, RecStatus.REJECTED)


def action_label(action: str | None) -> str:
    text = justification.ACTION_TEXT.get(action or "", (action or "").replace("_", " "))
    return text[:1].upper() + text[1:]


CHANNEL_LABEL = {
    "email": "Email",
    "sms": "SMS",
    "email_sms": "SMS + Email",
    "intermediary": "Broker / employer",
    "internal": "Internal task",
}


# ------------------------------------------------------------------ book view ---


class PolicyView(BaseModel):
    """One policy as the UI shows it in lists."""

    policy_id: str
    policy_number: str
    customer_id: str
    customer_name: str
    product_name: str
    line: str
    lifecycle_type: str
    channel_owner: str
    due_date: date | None  # expiry date, or the next lifecycle event for premium products
    days_to_due: int | None
    premium: int
    health: Health
    health_label: str
    at_risk: bool
    risk_score: float | None  # 0-10 from the retention agent's latest judgement
    issue: str | None  # the most pressing lifecycle event, in words
    rec_id: str | None
    rec_status: str | None
    suggested_action: str | None


class _Book:
    """Policies + their current assessment and latest recommendation, built once per request."""

    def __init__(self, s: DbSession) -> None:
        self.s = s
        self.as_of = today()
        self.policies = sorted(s.all(Policy), key=lambda p: p.id)
        self.customers = {c.id: c for c in s.all(Customer)}
        self.products = {p.code: p for p in s.all(Product)}
        self.assess: dict[str, RenewalAssessment] = {}
        self.recs: dict[str, Recommendation] = {}

    async def load(self) -> _Book:
        self.assess = await lifecycle.assess_many(
            self.s, await lifecycle.monitored_policies(self.s)
        )
        for r in self.s.where(Recommendation, lambda r: r.status not in _HISTORIC):
            cur = self.recs.get(r.subject_id)
            if cur is None or r.created_at > cur.created_at:
                self.recs[r.subject_id] = r
        return self

    def current_rec(self, p: Policy) -> Recommendation | None:
        """The latest recommendation if it belongs to the policy's current lifecycle event."""
        rec, a = self.recs.get(p.id), self.assess.get(p.id)
        if rec is None or a is None or rec.cycle_key != lifecycle.cycle_key(p.id, a):
            return None
        return rec

    def due_date(self, p: Policy) -> date | None:
        a = self.assess.get(p.id)
        if p.lifecycle_type in EXPIRY_LIFECYCLES:
            return p.end_date
        return (a.next_event_date if a else None) or p.next_event_date

    def view(self, p: Policy) -> PolicyView:
        a, rec = self.assess.get(p.id), self.current_rec(p)
        c = self.customers.get(p.customer_id)
        due = self.due_date(p)
        days = (due - self.as_of).days if due else None
        health: Health
        if p.status in (PolicyStatus.RENEWED, PolicyStatus.CANCELLED):
            health = p.status  # type: ignore[assignment]
        elif a and a.state == RenewalState.LAPSED:
            health = "lapsed"
        elif a and (a.state == RenewalState.IN_GRACE or a.signals.get("overdue_payments")):
            health = "overdue"
        elif a and a.skip_reason is None:
            health = "due_soon"
        else:
            health = "on_track"
        lr = (rec.decisions or {}).get("lapse_risk") if rec else None
        triggers = [t.type.value for t in a.triggers] if a else []
        at_risk = health in ("overdue", "lapsed") or "lapse_risk_signal" in triggers
        if rec and rec.band == "high":
            at_risk = True
        if at_risk and health in ("due_soon", "on_track"):
            health = "at_risk"
        return PolicyView(
            policy_id=p.id,
            policy_number=p.policy_number,
            customer_id=p.customer_id,
            customer_name=f"{c.first_name} {c.last_name}" if c else "?",
            product_name=self.products[p.product_code].name
            if p.product_code in self.products
            else p.product_code,
            line=p.line,
            lifecycle_type=p.lifecycle_type,
            channel_owner=p.channel_owner,
            due_date=due,
            days_to_due=days,
            premium=p.premium,
            health=health,
            health_label=HEALTH_LABEL[health],
            at_risk=at_risk,
            risk_score=round(lr["score"] * 10, 1) if lr and lr.get("score") is not None else None,
            issue=a.triggers[0].detail if a and a.triggers else None,
            rec_id=rec.id if rec else None,
            rec_status=rec.status if rec else None,
            suggested_action=action_label(rec.action)
            if rec
            else (action_label(a.allowed_actions[0]) if a and a.allowed_actions else None),
        )

    def views(self) -> list[PolicyView]:
        return [self.view(p) for p in self.policies]


async def _book(s: DbSession) -> _Book:
    return await _Book(s).load()


# ------------------------------------------------------------------ dashboard ---


class Kpis(BaseModel):
    total_policies: int
    in_force: int
    due_for_renewal: int
    at_risk: int
    renewal_rate_pct: float | None  # renewed / (renewed + lapsed + cancelled), ended terms


class TrendPoint(BaseModel):
    month: str  # YYYY-MM
    label: str  # "Oct"
    due: int  # renewals falling due that month (fixed-term and scheme policies)
    premium: int


class Slice(BaseModel):
    key: str
    label: str
    count: int


class Alert(BaseModel):
    policy_id: str
    customer_name: str
    issue: str
    severity: Literal["high", "medium", "low"]
    due_date: date | None
    rec_id: str | None


class DashboardOut(BaseModel):
    as_of: date
    kpis: Kpis
    trend: list[TrendPoint]
    status: list[Slice]
    alerts: list[Alert]


def _month_add(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, 1)


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(s: DbSession = Depends(db_session)) -> DashboardOut:
    book = await _book(s)
    views = book.views()
    live = [v for v in views if v.health not in ("renewed", "cancelled")]
    ended = Counter(p.status for p in book.policies)
    closed = ended["renewed"] + ended["lapsed"] + ended["cancelled"]

    start = _month_add(book.as_of.replace(day=1), -2)
    months = [_month_add(start, i) for i in range(8)]
    trend = []
    for m in months:
        nxt = _month_add(m, 1)
        due = [
            p
            for p in book.policies
            if p.lifecycle_type in EXPIRY_LIFECYCLES and m <= p.end_date < nxt
        ]
        trend.append(
            TrendPoint(
                month=m.strftime("%Y-%m"),
                label=m.strftime("%b"),
                due=len(due),
                premium=sum(p.premium for p in due),
            )
        )

    groups = {"on_track": 0, "due_soon": 0, "overdue": 0, "lapsed": 0}
    for v in live:
        key = "due_soon" if v.health == "at_risk" else v.health
        groups[key] = groups.get(key, 0) + 1
    rank = {"lapsed": 0, "overdue": 1, "at_risk": 2, "due_soon": 3}
    severity = {"lapsed": "high", "overdue": "high", "at_risk": "medium", "due_soon": "low"}
    alerts = sorted(
        (v for v in live if v.health in rank and v.issue),
        key=lambda v: (rank[v.health], v.days_to_due if v.days_to_due is not None else 9999),
    )
    return DashboardOut(
        as_of=book.as_of,
        kpis=Kpis(
            total_policies=len(book.policies),
            in_force=len(live),
            due_for_renewal=sum(v.health != "on_track" for v in live),
            at_risk=sum(v.at_risk for v in live),
            renewal_rate_pct=round(ended["renewed"] / closed * 100, 1) if closed else None,
        ),
        trend=trend,
        status=[Slice(key=k, label=HEALTH_LABEL[k], count=n) for k, n in groups.items()],
        alerts=[
            Alert(
                policy_id=v.policy_id,
                customer_name=v.customer_name,
                issue=v.issue or "",
                severity=severity[v.health],  # type: ignore[arg-type]
                due_date=v.due_date,
                rec_id=v.rec_id,
            )
            for v in alerts[:8]
        ],
    )


# ------------------------------------------------------------ renewal management ---


class PolicyPage(BaseModel):
    items: list[PolicyView]
    total: int
    limit: int
    offset: int
    counts: dict[str, int]  # per tab


VIEWS = ("all", "due_7", "due_30", "overdue", "at_risk")


def _in_view(v: PolicyView, view: str) -> bool:
    if view == "all":
        return True
    if view == "overdue":
        return v.health in ("overdue", "lapsed")
    if view == "at_risk":
        return v.at_risk
    days = 7 if view == "due_7" else 30
    return (
        v.health not in ("renewed", "cancelled")
        and v.days_to_due is not None
        and 0 <= v.days_to_due <= days
    )


@router.get("/policies", response_model=PolicyPage)
async def policies(
    view: Literal["all", "due_7", "due_30", "overdue", "at_risk"] = "all",
    q: str | None = Query(None, max_length=100),
    line: str | None = None,
    limit: int = Query(10, ge=1, le=200),
    offset: int = Query(0, ge=0),
    s: DbSession = Depends(db_session),
) -> PolicyPage:
    views = (await _book(s)).views()
    if line:
        views = [v for v in views if v.line == line]
    if q and q.strip():
        term = q.strip().lower()
        views = [
            v for v in views if term in v.customer_name.lower() or term in v.policy_number.lower()
        ]
    counts = {name: sum(_in_view(v, name) for v in views) for name in VIEWS}
    rows = [v for v in views if _in_view(v, view)]
    rows.sort(key=lambda v: (v.due_date is None, v.due_date or date.max, v.policy_number))
    return PolicyPage(
        items=rows[offset : offset + limit],
        total=len(rows),
        limit=limit,
        offset=offset,
        counts=counts,
    )


# --------------------------------------------------------------------- retention ---


class Indicator(BaseModel):
    key: str
    label: str
    count: int
    pct: float  # share of at-risk policies showing it


class RetentionOut(BaseModel):
    at_risk: int
    total: int
    pct_of_total: float
    bands: list[Slice]  # retention agent's risk bands (scored policies only)
    by_line: list[Slice]
    indicators: list[Indicator]
    customers: list[PolicyView]


INDICATORS = {
    "payment_issues": "Payment issues",
    "price_increase": "Renewal price increase",
    "service_complaints": "Service complaints",
    "incomplete_documents": "Incomplete documents",
    "recent_claims": "Recent claims",
}


def _indicators(sig: dict[str, Any]) -> set[str]:
    out = set()
    if sig.get("overdue_payments") or sig.get("failed_payments"):
        out.add("payment_issues")
    if (sig.get("premium_change_pct") or 0) >= rulebook.LAPSE_SIGNAL_PRICE_SHOCK_PCT:
        out.add("price_increase")
    if sig.get("service_complaints_12m"):
        out.add("service_complaints")
    if sig.get("docs_outstanding_count"):
        out.add("incomplete_documents")
    if (sig.get("claims_count_3y") or 0) >= 2:
        out.add("recent_claims")
    return out


@router.get("/retention", response_model=RetentionOut)
async def retention(s: DbSession = Depends(db_session)) -> RetentionOut:
    book = await _book(s)
    live = [v for v in book.views() if v.health not in ("renewed", "cancelled")]
    risky = [v for v in live if v.at_risk]
    seen: Counter[str] = Counter()
    for v in risky:
        a = book.assess.get(v.policy_id)
        seen.update(_indicators(a.signals if a else {}))
    bands = Counter(r.band for p in book.policies if (r := book.current_rec(p)) and r.band)
    risky.sort(
        key=lambda v: (-(v.risk_score or 0), v.days_to_due if v.days_to_due is not None else 9999)
    )
    for v in risky:  # reason: the agent's own top reason when it has judged the policy
        rec = book.recs.get(v.policy_id) if v.rec_id else None
        reasons = ((rec.decisions or {}).get("lapse_risk") or {}).get("reasons") if rec else None
        if reasons:
            v.issue = reasons[0].get("explanation") or v.issue
    return RetentionOut(
        at_risk=len(risky),
        total=len(live),
        pct_of_total=round(len(risky) / len(live) * 100, 1) if live else 0.0,
        bands=[
            Slice(key=b, label=b.capitalize(), count=bands.get(b, 0))
            for b in ("high", "medium", "low")
        ],
        by_line=[
            Slice(key=k, label=rulebook.LINES.get(k, {}).get("label", k), count=n)
            for k, n in Counter(v.line for v in risky).most_common()
        ],
        indicators=[
            Indicator(
                key=k,
                label=label,
                count=seen[k],
                pct=round(seen[k] / len(risky) * 100, 1) if risky else 0.0,
            )
            for k, label in sorted(INDICATORS.items(), key=lambda kv: -seen[kv[0]])
        ],
        customers=risky,
    )


# --------------------------------------------------------------- extra cover ---


class CoverItem(BaseModel):
    code: str
    name: str
    description: str
    line: str
    premium: int  # indicative annual base premium, minor units
    recommended: bool = False
    rationale: str | None = None


class CoverOut(BaseModel):
    policy: PolicyView
    email: str | None
    phone: str | None
    current: list[CoverItem]
    eligible: list[CoverItem]  # add-ons the rules allow for this customer now
    not_eligible_reason: str | None
    rec_id: str | None


def _cover_pick(rec: Recommendation | None) -> dict[str, Any]:
    """The recommendation agent's extra-cover pick (older records: the add-on offer)."""
    if rec is None:
        return {}
    if rec.cover_suggestion:
        return rec.cover_suggestion
    offer = rec.offer or {}
    return offer if offer.get("type") == "add_on" else {}


class CoverCandidate(BaseModel):
    policy: PolicyView
    eligible: int
    recommended: str | None  # add-on name the recommendation agent chose, if any


@router.get("/cover", response_model=list[CoverCandidate])
async def cover_candidates(s: DbSession = Depends(db_session)) -> list[CoverCandidate]:
    """Customers the rules allow extra cover for right now, agent-recommended ones first."""
    book = await _book(s)
    out = []
    for p in book.policies:
        a = book.assess.get(p.id)
        if not a or not a.add_on_options:
            continue
        pick = _cover_pick(book.current_rec(p))
        out.append(
            CoverCandidate(
                policy=book.view(p),
                eligible=len(a.add_on_options),
                recommended=pick.get("name"),
            )
        )
    out.sort(key=lambda c: (c.recommended is None, c.policy.customer_name))
    return out


@router.post("/cover/suggest", response_model=BatchOut, status_code=202)
async def suggest_cover(
    db: Database = Depends(get_database),
    runner: Runner | None = Depends(get_runner),
    actor: str | None = Depends(optional_actor),
) -> BatchOut:
    """Run the agents again for eligible customers who have no extra-cover pick yet (e.g.
    their message was prepared before). Their pending message is re-drafted too."""
    async with db.session() as s:
        book = await _book(s)
        batch = Batch(id=new_id("bat"), kind="cover_suggest", requested_by=actor)
        s.add(batch)
        runs = []
        for p in book.policies:
            a = book.assess.get(p.id)
            if not a or not a.add_on_options or _cover_pick(book.current_rec(p)):
                continue
            run, created, _ = await intake.enqueue_renewal(
                s, p, requested_by=actor, batch_id=batch.id
            )
            if run is not None and created:
                runs.append(run)
        out = BatchOut.of(batch, {"queued": len(runs)} if runs else {}, [r.id for r in runs])
    if runner and runs:
        runner.notify()
    return out


@router.get("/cover/{policy_id}", response_model=CoverOut)
async def cover(policy_id: str, s: DbSession = Depends(db_session)) -> CoverOut:
    book = await _book(s)
    p = next((x for x in book.policies if x.id == policy_id), None)
    if p is None:
        raise not_found("policy", policy_id)
    a = book.assess.get(p.id)
    rec = book.current_rec(p)
    pick = _cover_pick(rec)
    c = book.customers.get(p.customer_id)

    def item(code: str) -> CoverItem | None:
        prod = book.products.get(code)
        if prod is None:
            return None
        chosen = pick.get("code") == code
        return CoverItem(
            code=code,
            name=prod.name,
            description=prod.description,
            line=prod.line,
            premium=prod.base_premium,
            recommended=chosen,
            rationale=pick.get("rationale") if chosen else None,
        )

    current = [x for code in [p.product_code, *p.add_ons_held] if (x := item(code))]
    eligible = [x for code in (a.add_on_options if a else []) if (x := item(code))]
    reason = None
    if not eligible:
        product = book.products.get(p.product_code)
        if not (product and product.add_ons):
            reason = "This product has no extra cover in the catalogue."
        else:
            res = next(
                (
                    r
                    for r in (a.results if a else [])
                    if r.id.startswith("suitability.") and not r.passed
                ),
                None,
            )
            reason = res.reason if res else "No extra cover fits this customer right now."
    return CoverOut(
        policy=book.view(p),
        email=c.email if c else None,
        phone=c.phone if c else None,
        current=current,
        eligible=eligible,
        not_eligible_reason=reason,
        rec_id=rec.id if rec else None,
    )


# ------------------------------------------------------------------ workflow ---


class WorkflowItem(BaseModel):
    rec_id: str
    policy_id: str
    policy_number: str
    customer_name: str
    workflow: str
    action: str
    channel: str
    status: str  # awaiting_approval | scheduled | sent | failed | rejected | task_created
    status_label: str
    next_step: str
    link: dict[str, Any] | None
    updated_at: datetime


class WorkflowOut(BaseModel):
    steps: list[Slice]  # identify -> message -> send -> track
    items: list[WorkflowItem]
    total: int


NEXT_STEP = {
    "payment_reminder": "Check payment",
    "document_request": "Await documents",
    "reminder": "Track renewal",
    "retention_offer": "Track renewal",
    "reinstatement": "Track reinstatement",
    "plan_review": "Book the review",
    "add_on_offer": "Adviser follow-up",
    "service_follow_up": "Call the customer",
    "internal_task": "Team to contact customer",
}


@router.get("/workflow", response_model=WorkflowOut)
async def workflow(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    s: DbSession = Depends(db_session),
) -> WorkflowOut:
    book = await _book(s)
    msgs = {m.recommendation_id: m for m in s.all(Message)}
    crm = {a.recommendation_id for a in s.all(CrmActivity) if a.recommendation_id}
    items = []
    for p in book.policies:
        rec = book.recs.get(p.id)
        if rec is None:
            continue
        msg = msgs.get(rec.id)
        if rec.status == RecStatus.PENDING_APPROVAL:
            st, nxt = "awaiting_approval", "Approve or edit"
        elif rec.status == RecStatus.REJECTED:
            st, nxt = "rejected", "None (rejected)"
        elif msg is None:
            st, nxt = "task_created", NEXT_STEP.get(rec.action, "Follow up")
        elif msg.status in ("delivered", "sent"):
            st, nxt = "sent", NEXT_STEP.get(rec.action, "Track response")
        elif msg.status == "failed":
            st, nxt = "failed", "Retry the message"
        else:
            st, nxt = "scheduled", "Sending"
        items.append(
            WorkflowItem(
                rec_id=rec.id,
                policy_id=p.id,
                policy_number=p.policy_number,
                customer_name=book.view(p).customer_name,
                workflow=action_label(rec.action),
                action=rec.action,
                channel=CHANNEL_LABEL.get(rec.channel or "", rec.channel or "-"),
                status=st,
                status_label={
                    "awaiting_approval": "Awaiting approval",
                    "scheduled": "Scheduled",
                    "sent": "Sent",
                    "failed": "Failed",
                    "rejected": "Rejected",
                    "task_created": "Task created",
                }[st],
                next_step=nxt,
                link=rec.link,
                updated_at=(msg.sent_at if msg and msg.sent_at else rec.decided_at)
                or rec.created_at,
            )
        )
    counts = Counter(i.status for i in items)
    steps = [
        Slice(
            key="identify",
            label="Identify",
            count=sum(1 for a in book.assess.values() if a.skip_reason is None),
        ),
        Slice(key="message", label="Message", count=len(items)),
        Slice(key="send", label="Send", count=counts["sent"] + counts["scheduled"]),
        Slice(key="track", label="Track", count=len(crm)),
    ]
    if status:
        items = [i for i in items if i.status == status]
    items.sort(key=lambda i: i.updated_at, reverse=True)
    return WorkflowOut(steps=steps, items=items[offset : offset + limit], total=len(items))


# ------------------------------------------------------------- agent activity ---


class AgentStep(BaseModel):
    agent: str
    title: str
    status: Literal["completed", "skipped", "failed", "waiting"]
    at: datetime | None
    summary: str
    uses_ai: bool


class AgentTraceOut(BaseModel):
    rec_id: str
    policy_id: str
    policy_number: str
    customer_name: str
    action: str
    steps: list[AgentStep]
    data_sources: list[dict[str, str]]
    rules_models: list[dict[str, str]]
    outcome: str
    why: str


AGENTS = [
    ("renewal", "Renewal Agent"),
    ("retention", "Retention Agent"),
    ("recommendation", "Recommendation Agent"),
    ("personalisation", "Personalisation Agent"),
    ("workflow", "Workflow Agent"),
]


def _agent_summary(agent: str, p: dict[str, Any], rec: Recommendation) -> str:
    if agent == "renewal":
        trig = ", ".join(t.replace("_", " ") for t in p.get("triggers") or []) or "no events"
        allowed = ", ".join(action_label(x).lower() for x in p.get("allowed_actions") or [])
        state = str(p.get("state", "")).replace("_", " ")
        return f"Found {trig}; cover is {state}. Allowed: {allowed}."
    if agent == "retention":
        return (
            f"Rated risk of not renewing {p.get('band')} ({p.get('confidence')} confidence) "
            f"and chose {action_label(p.get('intervention')).lower()} by "
            f"{CHANNEL_LABEL.get(p.get('channel') or '', p.get('channel'))}."
            + (f" Discount {p['discount_pct']:g}%." if p.get("discount_pct") else "")
        )
    if agent == "recommendation":
        n = len(p.get("eligible") or [])
        if not p.get("code"):
            return "No extra cover fits this customer right now."
        name = (rec.cover_suggestion or rec.offer or {}).get("name") or p.get("code")
        when = (
            "offered in this message"
            if p.get("offered")
            else "kept for the adviser; this message handles something more urgent"
        )
        return f"Picked {name} as the best extra cover (from {n} eligible option(s)), {when}."
    if agent == "personalisation":
        if p.get("drafted"):
            channel = CHANNEL_LABEL.get(p.get("channel") or "", p.get("channel"))
            return f"Drafted a {channel} message ({p.get('chars')} chars) from the policy facts."
        return "No message needed: internal task for the team."
    return ""


@router.get("/agents/{rec_id}", response_model=AgentTraceOut)
async def agent_trace(rec_id: str, s: DbSession = Depends(db_session)) -> AgentTraceOut:
    rec = await s.get(Recommendation, rec_id)
    if rec is None:
        raise not_found("recommendation", rec_id)
    p = await s.get(Policy, rec.subject_id)
    c = await s.get(Customer, p.customer_id) if p else None
    events = sorted(
        s.where(AuditEvent, lambda e: e.run_id == rec.run_id or e.recommendation_id == rec.id),
        key=lambda e: e.id,
    )
    nodes = {
        e.event_type.removeprefix("node."): e for e in events if e.event_type.startswith("node.")
    }
    created = next((e for e in events if e.event_type == "recommendation.created"), None)
    decided = next(
        (e for e in events if e.event_type in (f"recommendation.{d}" for d in _DECIDED)), None
    )
    delivered = next((e for e in events if e.event_type == "message.delivered"), None)
    calls = s.where(LLMCall, lambda x: x.run_id == rec.run_id and x.status == "ok")
    steps = []
    for key, title in AGENTS:
        if key == "workflow":
            parts = [f"Queued '{action_label(rec.action).lower()}' for {rec.queue} approval"]
            if rec.link:
                parts.append(f"with link {rec.link['url']}")
            if decided:
                parts.append(
                    f"{decided.event_type.split('.')[1].replace('_', ' ')} by {decided.actor}"
                )
            if delivered:
                parts.append("message delivered and CRM updated")
            steps.append(
                AgentStep(
                    agent=key,
                    title=title,
                    status="completed" if created else "waiting",
                    at=(delivered or decided or created).ts if created else None,
                    summary="; ".join(parts) + ".",
                    uses_ai=False,
                )
            )
            continue
        ev = nodes.get(key)
        steps.append(
            AgentStep(
                agent=key,
                title=title,
                status="completed" if ev else "skipped",
                at=ev.ts if ev else None,
                summary=_agent_summary(key, ev.payload, rec) if ev else "Not needed for this case.",
                uses_ai=any(x.node == key for x in calls),
            )
        )
    models = sorted({f"{x.provider} · {x.model}" for x in calls})
    payments = len(s.where(Payment, lambda x: x.policy_id == rec.subject_id))
    j = justification.build(rec, events)
    return AgentTraceOut(
        rec_id=rec.id,
        policy_id=rec.subject_id,
        policy_number=p.policy_number if p else rec.subject_id,
        customer_name=f"{c.first_name} {c.last_name}" if c else "?",
        action=action_label(rec.action),
        steps=steps,
        data_sources=[
            {
                "name": "Policy system",
                "detail": f"policy, product, lifecycle ({p.lifecycle_type if p else '-'})",
            },
            {"name": "Billing", "detail": f"{payments} payment record(s)"},
            {"name": "CRM", "detail": "customer contact details and consents"},
            {
                "name": "Customer preferences",
                "detail": "preferred channel: "
                + ((c.preferred_channel if c else None) or "none stated"),
            },
        ],
        rules_models=[
            {"name": "Renewal rules", "detail": f"rulebook {rec.rulebook_version}"},
            {"name": "Retention model", "detail": ", ".join(m for m in models) or "not called"},
            {"name": "Recommendation rules", "detail": "add-on eligibility and suitability"},
            {"name": "Messaging checks", "detail": "consent, channel, amounts, tone"},
        ],
        outcome=j.get("headline") or "",
        why=j.get("why") or "",
    )
