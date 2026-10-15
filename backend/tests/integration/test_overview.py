"""The read models behind the eight UI pages."""

from __future__ import annotations

from backend.tests.integration.conftest import wait_batch


async def test_dashboard_and_policy_views(api_queue_only) -> None:
    c = api_queue_only
    d = (await c.get("/overview/dashboard")).json()
    k = d["kpis"]
    assert k["total_policies"] == 18 and k["due_for_renewal"] <= k["in_force"]
    assert sum(x["count"] for x in d["status"]) == k["in_force"]
    assert len(d["trend"]) == 8 and d["alerts"]

    page = (await c.get("/overview/policies", params={"view": "all", "limit": 5})).json()
    assert page["total"] == 18 and len(page["items"]) == 5
    assert page["counts"]["due_30"] >= page["counts"]["due_7"]
    overdue = (await c.get("/overview/policies", params={"view": "overdue", "limit": 50})).json()
    assert all(x["health"] in ("overdue", "lapsed") for x in overdue["items"])


async def test_retention_cover_workflow_agent_trace(api) -> None:
    c = api
    await wait_batch(c, (await c.post("/renewals/scan")).json()["id"])

    r = (await c.get("/overview/retention")).json()
    assert r["at_risk"] == len(r["customers"]) > 0
    assert r["customers"][0]["risk_score"] is not None  # scored by the retention agent

    cover = (await c.get("/overview/cover/pol_p14")).json()
    assert cover["current"][0]["code"] and cover["eligible"]
    assert (await c.get("/overview/cover/nope")).status_code == 404

    wf = (await c.get("/overview/workflow")).json()
    assert [s["key"] for s in wf["steps"]] == ["identify", "message", "send", "track"]
    assert wf["total"] == len(wf["items"]) > 0
    assert all(i["status"] == "awaiting_approval" for i in wf["items"])

    trace = (await c.get(f"/overview/agents/{wf['items'][0]['rec_id']}")).json()
    assert [s["agent"] for s in trace["steps"]] == [
        "renewal",
        "retention",
        "recommendation",
        "personalisation",
        "workflow",
    ]
    assert trace["steps"][0]["status"] == "completed" and trace["outcome"]


async def test_cover_candidates(api_queue_only) -> None:
    rows = (await api_queue_only.get("/overview/cover")).json()
    assert rows and all(r["eligible"] >= 1 for r in rows)
    assert "pol_p14" in {r["policy"]["policy_id"] for r in rows}


async def test_suggest_cover_reruns_only_customers_without_a_pick(api) -> None:
    c = api
    await wait_batch(c, (await c.post("/renewals/scan")).json()["id"])
    rows = (await c.get("/overview/cover")).json()
    assert rows and all(r["recommended"] for r in rows)  # every eligible customer has a pick
    again = (await c.post("/overview/cover/suggest")).json()
    assert again["run_ids"] == []  # nothing left to suggest


async def test_scan_can_rerun_pending_live(api) -> None:
    c = api
    first = (await c.post("/renewals/scan")).json()
    await wait_batch(c, first["id"])
    again = (await c.post("/renewals/scan")).json()
    assert again["run_ids"] == []  # default: pending messages are left alone
    live = (await c.post("/renewals/scan", json={"rerun_pending": True})).json()
    assert len(live["run_ids"]) == len(first["run_ids"])
    await wait_batch(c, live["id"])
    pending = (await c.get("/recommendations", params={"limit": 200})).json()
    assert pending["total"] == len(first["run_ids"])  # replaced, not duplicated


async def test_retention_filter_by_band(api) -> None:
    c = api
    await wait_batch(c, (await c.post("/renewals/scan")).json()["id"])
    r = (await c.get("/overview/retention")).json()
    for b in r["bands"]:
        listed = (await c.get("/overview/retention", params={"band": b["key"]})).json()
        assert len(listed["customers"]) == b["count"]
        assert all(x["risk_band"] == b["key"] for x in listed["customers"])
