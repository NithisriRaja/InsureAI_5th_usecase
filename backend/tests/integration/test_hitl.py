from __future__ import annotations

import asyncio

from backend.tests.integration.conftest import wait_batch


async def login(c, name: str, role: str) -> dict[str, str]:
    r = await c.post("/sessions", json={"name": name, "role": role})
    assert r.status_code == 201
    return {"X-Session-Id": r.json()["session_id"]}


async def test_hitl_end_to_end(api) -> None:
    batch = (await api.post("/renewals/scan")).json()
    await wait_batch(api, batch["id"])
    retention = await login(api, "Rita", "retention")
    adviser = await login(api, "Ada", "adviser")

    queue = (await api.get("/recommendations", params={"queue": "retention"})).json()
    rec = next(r for r in queue["items"] if r["subject_id"] == "pol_p03")
    detail = (await api.get(f"/recommendations/{rec['id']}")).json()
    assert detail["llm_calls"] and detail["audit"] and detail["subject"]["policy_number"]

    # no session -> 401, wrong role -> 403
    assert (await api.post(f"/approvals/{rec['id']}/approve")).status_code == 401
    assert (await api.post(f"/approvals/{rec['id']}/approve", headers=adviser)).status_code == 403

    # edit breaking the discount cap -> 422 with rule id
    r = await api.post(
        f"/approvals/{rec['id']}/edit", headers=retention, json={"edits": {"discount_pct": 30}}
    )
    assert r.status_code == 422
    assert any(d["rule"] == "renewal.discount_cap" for d in r.json()["error"]["details"])

    # concurrent approvals: exactly one wins
    results = await asyncio.gather(
        *(
            api.post(
                f"/approvals/{rec['id']}/edit",
                headers=retention,
                json={
                    "expected_version": rec["version"],
                    "edits": {
                        "discount_pct": 10,
                        "draft_message": "Hi Grace, renew today with 10% off.",
                    },
                },
            )
            for _ in range(5)
        )
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409, 409, 409, 409], codes
    winner = next(r.json() for r in results if r.status_code == 200)
    assert winner["status"] == "approved_with_edits" and winner["message_id"]

    for _ in range(60):
        msgs = (await api.get("/messages")).json()["items"]
        if msgs and msgs[0]["status"] == "delivered":
            break
        await asyncio.sleep(0.05)
    assert msgs[0]["status"] == "delivered" and "10% off" in msgs[0]["body"]

    detail = (await api.get(f"/recommendations/{rec['id']}")).json()
    assert detail["approval"]["original"]["offer"]["discount_pct"] == 5
    assert detail["offer"]["discount_pct"] == 10 and detail["decided_by_user"]["name"] == "Rita"

    # reject needs a reason
    other = next(r for r in queue["items"] if r["subject_id"] == "pol_p01")
    assert (
        await api.post(f"/approvals/{other['id']}/reject", headers=retention, json={})
    ).status_code == 422
    r = await api.post(
        f"/approvals/{other['id']}/reject",
        headers=retention,
        json={"reason": "Customer already called us"},
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected"

    stats = (await api.get("/stats")).json()
    assert stats["edits"] == 1 and stats["llm"]["calls"] > 0


async def test_stale_after_policy_renewed(api) -> None:
    batch = (await api.post("/renewals/scan")).json()
    await wait_batch(api, batch["id"])
    h = await login(api, "Admin", "admin")
    rec = next(
        r
        for r in (await api.get("/recommendations")).json()["items"]
        if r["subject_id"] == "pol_p02"
    )
    from backend.db.models import Policy

    async with api.app.state.db.session() as s:
        (await s.get(Policy, "pol_p02")).status = "renewed"
    r = await api.post(f"/approvals/{rec['id']}/approve", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale"


async def test_session_survives_app_restart(seeded_db, llm_switch) -> None:
    from backend.tests.integration.conftest import _client

    async for c in _client(seeded_db, llm_switch, start_runner=False):
        h = await login(c, "Una", "adviser")
    async for c in _client(seeded_db, llm_switch, start_runner=False):
        me = await c.get("/sessions/me", headers=h)
        assert me.status_code == 200 and me.json()["role"] == "adviser"
        assert (await c.get("/sessions/me", headers={"X-Session-Id": "bogus"})).status_code == 401


async def test_workflow_sends_link_and_updates_crm(api) -> None:
    await wait_batch(api, (await api.post("/renewals/scan")).json()["id"])
    h = await login(api, "Rita", "retention")
    rec = next(
        r
        for r in (await api.get("/recommendations", params={"queue": "retention"})).json()["items"]
        if r["subject_id"] == "pol_p03"
    )
    detail = (await api.get(f"/recommendations/{rec['id']}")).json()
    assert detail["link"]["url"].endswith(detail["subject"]["policy_number"])
    r = await api.post(f"/approvals/{rec['id']}/approve", headers=h, json={})
    assert r.status_code == 200 and r.json()["message_id"]

    for _ in range(60):
        crm = (await api.get("/renewals/pol_p03/crm")).json()
        if any(a["kind"] == "message_delivered" for a in crm):
            break
        await asyncio.sleep(0.05)
    kinds = {a["kind"] for a in crm}
    assert {"follow_up_approved", "message_delivered"} <= kinds
    msg = next(
        m for m in (await api.get("/messages")).json()["items"] if m["id"] == r.json()["message_id"]
    )
    assert detail["link"]["url"] in msg["body"]


async def test_documents_received_clears_the_chase(api) -> None:
    policy = (await api.get("/renewals/pol_p02")).json()
    doc = policy["docs_outstanding"][0]
    body = {"received": [doc]}
    assert (await api.post("/renewals/pol_p02/documents", json=body)).status_code == 401
    h = await login(api, "Rita", "retention")
    bad = await api.post("/renewals/pol_p02/documents", headers=h, json={"received": ["nope"]})
    assert bad.status_code == 422
    r = await api.post("/renewals/pol_p02/documents", headers=h, json=body)
    assert r.status_code == 200 and doc not in r.json()["docs_outstanding"]
    assert doc not in (await api.get("/renewals/pol_p02")).json()["docs_outstanding"]
    crm = (await api.get("/renewals/pol_p02/crm")).json()
    assert crm[0]["kind"] == "documents_received" and doc in crm[0]["summary"]
