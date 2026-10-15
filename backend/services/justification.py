"""Explain a stored recommendation to the approver: which rules and AI judgements led to it.

Built on read from what the run already stored (rule results, LLM decisions, run audit), so
it needs no extra LLM call and works for every recommendation ever created. The output is a
decision path (one step per stage, each marked as a hard rule, an AI judgement or fixed
policy), the criteria met / not met, and what the approver should check before deciding.
"""

from __future__ import annotations

from typing import Any

from backend import rulebook
from backend.enums import Action, ChannelOwner, Queue

ACTION_TEXT = {
    Action.REMINDER: "send a renewal reminder",
    Action.PAYMENT_REMINDER: "send a payment reminder",
    Action.DOCUMENT_REQUEST: "request outstanding documents",
    Action.PLAN_REVIEW: "book a plan review",
    Action.SERVICE_FOLLOW_UP: "service follow-up",
    Action.RETENTION_OFFER: "make a retention offer",
    Action.ADD_ON_OFFER: "suggest extra cover",
    Action.REINSTATEMENT: "offer reinstatement",
    Action.INTERNAL_TASK: "internal task for the team",
}
QUEUE_TEXT = {
    Queue.ADVISER: "Adviser",
    Queue.RETENTION: "Retention",
}
CHANNEL_TEXT = {"sms": "SMS", "email": "email", "whatsapp": "WhatsApp", "phone": "phone"}
OWNER_TEXT = {o.value: o.value.replace("_", " ") for o in ChannelOwner}


def _act(action: str) -> str:
    return ACTION_TEXT.get(action, action.replace("_", " "))  # type: ignore[call-overload]


def _human(key: str) -> str:
    return key.replace("declared.", "").replace("_", " ")


def _step(
    key: str,
    title: str,
    basis: str,
    status: str,
    outcome: str,
    details: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "basis": basis,  # rule | ai | policy
        "status": status,  # pass | fail | warn | skipped | info
        "outcome": outcome,
        "details": [d for d in details or [] if d],
    }


def _rules(rules: list[dict[str, Any]], *prefixes: str) -> list[dict[str, Any]]:
    return [r for r in rules if r.get("id", "").startswith(prefixes)]


def _ai_reasons(d: dict[str, Any] | None, signals: dict[str, Any], limit: int = 3) -> list[str]:
    out = []
    for r in (d or {}).get("reasons", [])[:limit]:
        sig = r.get("signal", "")
        val = signals.get(sig)
        shown = f" = {val}" if val is not None and not isinstance(val, (dict, list)) else ""
        out.append(f"{_human(sig)}{shown}: {r.get('explanation', '')}")
    return out


def _ai_line(name: str, d: dict[str, Any] | None) -> str:
    if not d:
        return ""
    score = d.get("score")
    pct = f", score {round(score * 100)}/100" if isinstance(score, (int, float)) else ""
    return f"{name}: {d.get('band')} ({d.get('confidence')} confidence{pct})"


def _routing(rec: Any) -> dict[str, Any]:
    entry = rulebook.APPROVAL_MATRIX.get(rec.action) or {}
    base = entry.get("queue")
    details = [
        f"Approval matrix sends '{_act(rec.action)}' to the {QUEUE_TEXT.get(base, base)} queue."
    ]
    if base and base != rec.queue:
        if rec.queue == Queue.ADVISER:
            details.append("Moved to the Adviser queue: an adviser owns this relationship.")
        elif rec.queue == Queue.RETENTION:
            details.append("Moved to Retention: not adviser-owned and not a regulated product.")
    if rec.channel == "intermediary":
        details.append(
            f"Relationship owned by the {OWNER_TEXT.get(rec.channel_owner or '', 'intermediary')}: "
            "contact goes through them, never directly to the customer."
        )
    if entry.get("regulated_advice"):
        details.append("Regulated advice: needs a licensed adviser's approval.")
    return _step(
        "routing",
        "Who approves",
        "policy",
        "info",
        f"{QUEUE_TEXT.get(rec.queue, rec.queue)} queue, {rec.priority} priority",
        details,
    )


def _fairness(rec: Any) -> dict[str, Any]:
    f = rec.fairness or {}
    cats = f.get("categories") or []
    details = ["Protected traits (gender, religion, nationality, ...) are never sent to the AI."]
    if f.get("redactions"):
        details.append(
            f"{f['redactions']} sensitive detail(s) removed from notes before the AI saw them"
            + (f" ({', '.join(cats)})." if cats else ".")
        )
    for v in f.get("violations") or []:
        details.append(f"Violation: {v}")
    ok = f.get("passed", True)
    return _step(
        "fairness",
        "Fairness check",
        "rule",
        "pass" if ok else "fail",
        "Passed" if ok else "Failed",
        details,
    )


# --------------------------------------------------------------------- renewal


def _renewal(rec: Any, events: list[Any]) -> tuple[list[dict[str, Any]], str, list[str]]:
    rules: list[dict[str, Any]] = rec.rule_results or []
    dec: dict[str, Any] = rec.decisions or {}
    sig: dict[str, Any] = rec.signals or {}
    node = next((e.payload for e in events if e.event_type == "node.renewal" and e.payload), {})
    steps: list[dict[str, Any]] = []

    lc = _rules(rules, "renewal.lifecycle")
    trig = [t.get("detail") or t.get("type", "") for t in rec.triggers or []]
    steps.append(
        _step(
            "lifecycle",
            "Policy status and triggers",
            "rule",
            "pass",
            f"{(node.get('state') or '').replace('_', ' ') or 'in scope'}; "
            f"{len(trig)} trigger(s) need attention",
            [r["reason"] for r in lc] + trig,
        )
    )

    allowed = node.get("allowed_actions") or []
    elig = _rules(rules, "renewal.offer_eligibility", "suitability.", "consent.")
    details = []
    if allowed:
        details.append("Allowed: " + ", ".join(_act(a) for a in allowed) + ".")
    if node.get("max_discount_pct"):
        details.append(f"Maximum discount for this customer: {node['max_discount_pct']}%.")
    if node.get("add_on_options"):
        details.append(f"Suitable extra cover: {', '.join(node['add_on_options'])}.")
    details += [r["reason"] for r in elig]
    steps.append(
        _step(
            "allowed",
            "What the rules allow",
            "rule",
            "info",
            f"{len(allowed)} permitted next step(s)" if allowed else "See rule results",
            details,
        )
    )

    lr = dec.get("lapse_risk") or {}
    steps.append(
        _step(
            "lapse",
            "Risk of not renewing",
            "ai",
            "info",
            _ai_line("Rated", lr) or "Not rated",
            _ai_reasons(lr, sig),
        )
    )

    choice = [
        f"Picked '{_act(rec.action)}' via {rec.channel or 'no channel'} "
        "from the allowed list only.",
        lr.get("rationale", ""),
        "Choice re-validated against the rules (action, channel, discount cap, add-on) "
        "before it was stored.",
    ]
    offer = rec.offer or {}
    if offer.get("type") == "discount":
        choice.append(
            f"Discount {offer.get('discount_pct')}% is within the {offer.get('max_discount_pct')}% "
            "cap."
        )
    steps.append(_step("choice", "Chosen next step", "ai", "pass", _act(rec.action), choice))

    if rec.draft_message:
        steps.append(
            _step(
                "message",
                "Draft message",
                "ai",
                "info",
                f"{rec.channel} draft ready, sent only after approval",
                ["Written only from the facts this step needs (no other policy data)."],
            )
        )

    because = f"the rules allow it and the AI rated non-renewal risk {lr.get('band', '?')}"
    if rec.triggers:
        types = ", ".join(_human(t.get("type", "")) for t in rec.triggers)
        because = f"{because} (triggers: {types})"
    return steps, because, _checks_common(rec, rules)


# ------------------------------------------------------------ approver checks


def _tidy(text: str) -> str:
    """'Premium up 18%.; Two complaints.' -> 'Premium up 18% · Two complaints'."""
    parts = [p.strip().rstrip(".").strip() for p in text.split(";")]
    return " · ".join(p for p in parts if p)


def _item(kind: str, title: str, detail: str = "") -> dict[str, str]:
    return {"kind": kind, "title": title, "detail": detail}


def _split_reason(reason: str) -> tuple[str, str]:
    """'Prefix: rest' -> (prefix, rest) when the prefix is a short label."""
    head, sep, rest = reason.partition(":")
    if sep and 0 < len(head) <= 40:
        detail = _tidy(rest)
        return head.strip(), detail[:1].upper() + detail[1:]
    return _tidy(reason), ""


def _checks_common(rec: Any, rules: list[dict[str, Any]]) -> list[dict[str, str]]:
    """What the approver should confirm before approving, as short title + detail."""
    items: list[dict[str, str]] = []
    for r in rec.review_reasons or []:
        text = str(r)
        if text.startswith("LLM flagged:"):
            items.append(_item("flag", "AI flagged a concern", text.split(":", 1)[1].strip()))
        else:
            title, detail = _split_reason(text)
            items.append(_item("rule", title, detail))
    seen = " ".join(i["title"] + " " + i["detail"] for i in items)
    for r in rules:
        if not r["passed"] and r["severity"] == "warn" and _tidy(r["reason"]) not in seen:
            title, detail = _split_reason(r["reason"])
            items.append(_item("rule", title, detail))
    if rec.confidence in ("low", "medium"):
        items.append(
            _item(
                "confidence",
                f"AI is only {rec.confidence}-confident",
                "Check the key facts in 'Facts used' before you approve.",
            )
        )
    offer = rec.offer or {}
    if offer.get("type") == "discount":
        items.append(
            _item(
                "offer",
                f"{_num(offer.get('discount_pct'))}% discount is justified",
                f"Cap is {_num(offer.get('max_discount_pct'))}%. The AI chose the smallest it "
                "expects to work.",
            )
        )
    if offer.get("type") == "add_on":
        items.append(
            _item(
                "offer",
                "Extra cover suits them",
                "This is regulated advice: confirm it fits the customer's needs.",
            )
        )
    if rec.draft_message:
        items.append(
            _item(
                "message",
                "The draft reads right",
                "It is sent exactly as approved. Read it in the Message tab.",
            )
        )
    if rec.channel == "intermediary":
        items.append(
            _item(
                "channel",
                "Goes via the broker / employer",
                "Not straight to the customer: they own the relationship.",
            )
        )
    return items


# The business concern each step protects, shown next to it.
ASPECT = {
    "lifecycle": "Policy lifecycle",
    "allowed": "Guardrails",
    "lapse": "Retention",
    "choice": "Next best action",
    "message": "Customer contact",
    "routing": "Governance",
    "fairness": "Fair treatment",
}


def _num(x: Any) -> str:
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def headline(rec: Any) -> str:
    """One plain, punchy line a busy approver can act on."""
    sig: dict[str, Any] = rec.signals or {}
    a = rec.action
    overdue = sig.get("overdue_payments") or 0
    days = sig.get("days_to_expiry")
    change = sig.get("premium_change_pct")
    offer = rec.offer or {}
    if a == Action.PAYMENT_REMINDER:
        return f"Money's late ({overdue} overdue). Nudge now, before cover slips."
    if a == Action.REINSTATEMENT:
        return "Cover has lapsed. Offer a clean way back in before they shop elsewhere."
    if a == Action.DOCUMENT_REQUEST:
        n = sig.get("docs_outstanding_count") or 0
        docs = "a document" if n == 1 else f"{n} documents" if n else "documents"
        return f"Paperwork gap: {docs} missing. Chase them so renewal doesn't stall."
    if a == Action.RETENTION_OFFER:
        why = (
            f"price up {_num(change)}%"
            if isinstance(change, (int, float)) and change > 0
            else "wobbly"
        )
        return (
            f"Flight risk ({why}). A {_num(offer.get('discount_pct'))}% sweetener should keep "
            f"them, inside the {_num(offer.get('max_discount_pct'))}% cap."
        )
    if a == Action.ADD_ON_OFFER:
        return f"Happy customer, gap in cover: suggest {offer.get('name') or 'extra cover'}."
    if a == Action.SERVICE_FOLLOW_UP:
        return "Something's bugging this customer. A human follow-up beats a discount here."
    if a == Action.PLAN_REVIEW:
        return "Review time. A quick check-in keeps the plan matched to their life."
    if a == Action.INTERNAL_TASK:
        return "No channel we're allowed to use. The team handles this one in-house."
    if a == Action.REMINDER:
        when = f"{days} days out" if isinstance(days, int) and days >= 0 else "coming up"
        return f"Renewal {when}, low drama. A friendly reminder is all it needs."
    return f"Next step: {_act(a)}."


def _sentence(text: str) -> str:
    text = text.strip().rstrip(".;:").strip()
    return text[:1].upper() + text[1:] + "." if text else ""


def _plural(n: Any, word: str) -> str:
    return f"{'no' if n == 0 else _num(n)} {word}" + ("" if n == 1 else "s")


def _fact(key: str, v: Any, currency: str) -> str:
    """One customer data point in plain words, e.g. '3 quote requests in the last 30 days'."""
    if v is None or v == "" or isinstance(v, dict):
        return ""
    if key in ("age_band", "customer_age_band"):
        return f"aged {_human(str(v))}"
    if key in ("sum_insured", "premium"):
        return f"{_human(key)} {currency} {v:,.0f}".strip() if isinstance(v, (int, float)) else ""
    if key == "days_to_expiry" and isinstance(v, (int, float)):
        if v == 0:
            return "term ends today"
        return (
            f"term ends in {_plural(v, 'day')}" if v > 0 else f"term ended {_plural(-v, 'day')} ago"
        )
    if key == "premium_change_pct" and isinstance(v, (int, float)):
        if v == 0:
            return "premium unchanged"
        return f"premium up {_num(v)}%" if v > 0 else f"premium down {_num(-v)}%"
    if key == "auto_renew":
        return "auto-renew on" if v else "auto-renew off"
    if key == "service_complaints_12m":
        return f"{_plural(v, 'service complaint')} in 12 months"
    if key == "claims_count_3y":
        return f"{_plural(v, 'claim')} in 3 years"
    if key == "tenure_years":
        return f"{_plural(v, 'year')} as a customer"
    if key == "grace_days":
        return f"{_num(v)}-day grace period"
    if key in ("overdue_payments", "failed_payments"):
        return f"{_plural(v, _human(key)[:-1])}" if v else f"no {_human(key)}"
    if key == "days_premium_overdue":
        return f"premium {_plural(v, 'day')} overdue"
    if key == "days_to_review" and isinstance(v, (int, float)):
        return (
            f"review due in {_plural(v, 'day')}"
            if v >= 0
            else f"review {_plural(-v, 'day')} overdue"
        )
    if key == "docs_outstanding_count":
        return f"{_plural(v, 'document')} outstanding"
    if isinstance(v, bool):
        return f"{_human(key)}: {'yes' if v else 'no'}"
    if isinstance(v, list):
        return f"{_human(key)}: {', '.join(_human(str(x)) for x in v) or 'none'}"
    return f"{_human(key)} {_human(str(v))}"


def _record(sig: dict[str, Any], keys: list[str], limit: int = 4) -> str:
    """'This customer's record shows a, b, c and d', from the first usable keys."""
    cur = str(sig.get("currency") or "")
    facts: list[str] = []
    for k in dict.fromkeys(keys):
        f = _fact(k, sig.get(k), cur)
        if f:
            facts.append(f)
        if len(facts) == limit:
            break
    if not facts:
        return ""
    listed = facts[0] if len(facts) == 1 else ", ".join(facts[:-1]) + " and " + facts[-1]
    return f"This customer's record shows {listed}"


def _reason_keys(*decisions: dict[str, Any] | None) -> list[str]:
    return [r.get("signal", "") for d in decisions for r in (d or {}).get("reasons") or []]


def why(rec: Any) -> str:
    """A short paragraph (3-4 sentences) on why the agent chose this action, quoting the
    customer data it acted on so the approver can see the decision matches the record."""
    dec: dict[str, Any] = rec.decisions or {}
    sig: dict[str, Any] = rec.signals or {}
    a = rec.action
    out: list[str] = []
    lr = dec.get("lapse_risk")
    triggers = [_human(t.get("type", "")) for t in rec.triggers or []]
    out.append(
        f"This {_human(str(sig.get('line') or 'insurance'))} policy came up for review"
        + (f" because of {', '.join(triggers)}" if triggers else "")
    )
    out.append(
        _record(
            sig,
            _reason_keys(lr)
            + ["days_to_expiry", "premium_change_pct", "tenure_years", "overdue_payments"],
        )
    )
    if lr:
        out.append(
            f"Weighing these, the AI rated the risk of not renewing {lr.get('band')} "
            f"with {lr.get('confidence')} confidence"
        )
    offer = rec.offer or {}
    pick = f"From the next steps the rules allow, it chose to {_act(a)}"
    if offer.get("type") == "discount":
        pick += (
            f" with a {_num(offer.get('discount_pct'))}% discount, inside the "
            f"{_num(offer.get('max_discount_pct'))}% cap"
        )
    elif offer.get("type") == "add_on":
        pick += f", suggesting {offer.get('name') or offer.get('code')}"
    if rec.channel == "intermediary":
        pick += ", handled through the broker or employer who owns the relationship"
    elif rec.channel:
        pick += f", sent by {CHANNEL_TEXT.get(rec.channel, rec.channel.replace('_', ' '))}"
    out.append(pick)
    return " ".join(_sentence(s) for s in out if s.strip())


def _cited_facts(rec: Any) -> list[dict[str, Any]]:
    """Every fact an AI judgement leaned on, with its value and the AI's own words."""
    sig: dict[str, Any] = rec.signals or {}
    out: list[dict[str, Any]] = []
    names = {"lapse_risk": "Renewal risk"}
    for key, label in names.items():
        for r in (rec.decisions or {}).get(key, {}).get("reasons", []) or []:
            s = r.get("signal", "")
            out.append(
                {
                    "signal": s,
                    "value": sig.get(s),
                    "explanation": r.get("explanation", ""),
                    "judgement": label,
                }
            )
    return out


def build(rec: Any, events: list[Any]) -> dict[str, Any]:
    steps, because, checks = _renewal(rec, events)
    steps += [_routing(rec), _fairness(rec)]
    for s in steps:
        s["aspect"] = ASPECT.get(s["key"], "")
    rule_steps = [s for s in steps if s["basis"] == "rule"]
    summary = f"Recommends: {_act(rec.action)}" + (f", because {because}." if because else ".")
    return {
        "headline": headline(rec),
        "why": why(rec),
        "summary": summary[0].upper() + summary[1:],
        "cited_facts": _cited_facts(rec),
        "steps": steps,
        "criteria_met": [s["title"] for s in rule_steps if s["status"] == "pass"],
        "criteria_not_met": [s["title"] for s in rule_steps if s["status"] in ("fail", "warn")],
        "approver_items": checks,
        "approver_checks": [
            f"{c['title']}: {c['detail']}" if c["detail"] else c["title"] for c in checks
        ],
        "allowed_actions": next(
            (
                e.payload.get("allowed_actions") or []
                for e in events
                if e.event_type == "node.renewal" and e.payload
            ),
            None,
        ),
        "ai_used": any(s["basis"] == "ai" and s["status"] != "skipped" for s in steps),
        "rulebook_version": rec.rulebook_version,
    }
