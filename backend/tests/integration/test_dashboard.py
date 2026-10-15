from __future__ import annotations

from backend.tests.integration.conftest import wait_batch


async def test_dashboard_matches_list_endpoints(api_queue_only) -> None:
    c = api_queue_only
    d = (await c.get("/dashboard")).json()

    pending = (await c.get("/recommendations")).json()
    assert d["recommendations"]["pending"] == pending["total"]
    assert (
        sum(q["high"] + q["medium"] + q["low"] for q in d["recommendations"]["pending_by_queue"])
        == pending["total"]
    )

    due = (await c.get("/renewals")).json()
    in_window = [p for p in due["items"] if p["status"] not in ("renewed", "cancelled")]
    assert d["policies"]["due_for_renewal"] <= len(in_window)
    assert {b["key"] for b in d["policies"]["expiry"]} == {
        "past",
        "0_7",
        "8_30",
        "31_window",
        "later",
    }
    assert d["decisions"]["approval_rate_pct"] is None  # fresh seed: nothing decided yet


async def test_dashboard_renewal_block(api) -> None:
    c = api
    await wait_batch(c, (await c.post("/renewals/scan")).json()["id"])

    d = (await c.get("/dashboard")).json()
    ren = d["renewal"]
    assert ren["review"]["pending"] == (await c.get("/recommendations")).json()["total"]
    assert ren["checked"] <= ren["due"] == d["policies"]["due_for_renewal"]
    assert sum(x["count"] for x in ren["next_steps"]) >= ren["checked"]
    offers = [x for x in ren["next_steps"] if x["key"] == "retention_offer"]
    assert ren["offers"]["count"] == (offers[0]["count"] if offers else 0)
    assert ren["offers"]["customer_savings"] >= 0


async def test_messages_filter_by_line(api_queue_only) -> None:
    r = (await api_queue_only.get("/messages", params={"line": "motor"})).json()
    assert all(m["subject_type"] == "policy" for m in r["items"])


async def test_renewal_and_recommendation_search(api_queue_only) -> None:
    c = api_queue_only
    book = (await c.get("/renewals", params={"window_days": 365, "limit": 200})).json()["items"]
    p = book[0]
    hit = (await c.get("/renewals", params={"window_days": 365, "q": p["policy_number"]})).json()
    assert [x["policy_id"] for x in hit["items"]] == [p["policy_id"]]
    line = (await c.get("/renewals", params={"window_days": 365, "line": p["line"]})).json()
    assert all(x["line"] == p["line"] for x in line["items"])

    none = (await c.get("/recommendations", params={"q": "zz-no-such-person", "status": ""})).json()
    assert none["total"] == 0


async def test_kpi_drill_and_line_filters(api) -> None:
    c = api
    await wait_batch(c, (await c.post("/renewals/scan")).json()["id"])
    lapse = (await c.get("/kpi/renewal/lapse")).json()
    assert lapse["total"] == sum(g["count"] for g in lapse["groups"]) > 0
    assert all(p["headline"] for g in lapse["groups"] for p in g["people"])
    assert (await c.get("/kpi/renewal/nope")).status_code == 422
    assert (await c.get("/kpi/acquisition/risk")).status_code == 404

    line = lapse["groups"][0]["people"][0]["line"]
    by_line = (await c.get("/kpi/renewal/lapse", params={"line": line})).json()
    assert by_line["total"] > 0
    assert all(p["line"] == line for g in by_line["groups"] for p in g["people"])
    recs = (await c.get("/recommendations", params={"line": line})).json()
    assert recs["total"] > 0 and {r["line"] for r in recs["items"]} == {line}
    detail = (await c.get(f"/recommendations/{recs['items'][0]['id']}")).json()
    assert detail["justification"]["headline"] and detail["line"] == line
