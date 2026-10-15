from __future__ import annotations

import asyncio

from backend.tests.integration.conftest import wait_batch, wait_run

# Seed (as_of 2026-10-13). Expiry lifecycles: P01-P06, P09, P11 inside the 45-day notice
# window, P12 (group scheme) inside its 90-day window; P07 renewed + P08 cancelled are
# reported as skipped; P10 is beyond the window. Premium lifecycles: P13 missed premium,
# P14 review due, P15 lapsed, P16 milestone, P18 review overdue; P17 has no event.
EXPECTED_QUEUED = {
    "pol_p01",
    "pol_p02",
    "pol_p03",
    "pol_p04",
    "pol_p05",
    "pol_p06",
    "pol_p09",
    "pol_p11",
    "pol_p12",
    "pol_p13",
    "pol_p14",
    "pol_p15",
    "pol_p16",
    "pol_p18",
}


async def test_scan_processes_batch(api) -> None:
    r = await api.post("/renewals/scan")
    assert r.status_code == 202
    batch = r.json()
    assert {s["reason"] for s in batch["skipped"]} == {"already_renewed", "cancelled"}
    assert len(batch["run_ids"]) == len(EXPECTED_QUEUED)

    done = await wait_batch(api, batch["id"])
    assert done["counts"] == {"succeeded": len(EXPECTED_QUEUED)}

    work = (await api.get("/renewals")).json()
    by_id = {i["policy_id"]: i for i in work["items"]}
    assert set(by_id) == EXPECTED_QUEUED | {"pol_p07", "pol_p08"}
    for pid in EXPECTED_QUEUED:
        assert by_id[pid]["latest_recommendation"]["status"] == "pending_approval"
    assert by_id["pol_p09"]["latest_recommendation"]["action"] == "internal_task"
    assert by_id["pol_p01"]["overdue_payments"] == 2
    assert by_id["pol_p01"]["channel_owner"] == "broker"
    assert by_id["pol_p03"]["premium_change_pct"] == 18.0
    assert by_id["pol_p13"]["triggers"] == ["premium_missed"]
    assert by_id["pol_p13"]["days_to_expiry"] is None  # no expiry for premium products
    assert by_id["pol_p16"]["next_event_type"] == "milestone"


async def test_worklist_filters_by_lifecycle_and_owner(api_queue_only) -> None:
    c = api_queue_only
    premium = (await c.get("/renewals", params={"lifecycle_type": "premium_continuation"})).json()
    assert {i["policy_id"] for i in premium["items"]} == {"pol_p13", "pol_p14", "pol_p15"}
    advisers = (await c.get("/renewals", params={"channel_owner": "adviser"})).json()
    assert all(i["intermediary"] for i in advisers["items"])


async def test_rescan_does_not_duplicate(api) -> None:
    first = (await api.post("/renewals/scan")).json()
    await wait_batch(api, first["id"])
    second = (await api.post("/renewals/scan")).json()
    assert second["run_ids"] == []
    reasons = {s["subject_id"]: s["reason"] for s in second["skipped"]}
    assert all(reasons[p] == "open_recommendation" for p in EXPECTED_QUEUED)


async def test_concurrent_scans_queue_each_policy_once(api_queue_only) -> None:
    results = await asyncio.gather(*(api_queue_only.post("/renewals/scan") for _ in range(4)))
    queued = [rid for r in results for rid in r.json()["run_ids"]]
    assert len(queued) == len(EXPECTED_QUEUED)
    runs = (await api_queue_only.get("/runs", params={"status": "queued"})).json()
    assert {r["subject_id"] for r in runs["items"]} == EXPECTED_QUEUED


async def test_custom_window(api_queue_only) -> None:
    batch = (await api_queue_only.post("/renewals/scan", json={"window_days": 100})).json()
    assert len(batch["run_ids"]) == len(EXPECTED_QUEUED) + 1  # P10 (+90d) now included


async def test_health(api) -> None:
    h = (await api.get("/health")).json()
    assert h["status"] == "ok" and h["runner"]["running"] and h["as_of"] == "2026-10-13"


async def test_policy_profile_and_single_run(api) -> None:
    detail = (await api.get("/renewals/pol_p01")).json()
    assert detail["policy_number"] == "MOT-2025-01000"
    assert detail["product_name"] == "Motor Comprehensive"
    assert detail["in_window"] is True and detail["skip_reason"] is None
    assert set(detail["allowed_actions"]) == {"reminder", "payment_reminder"}
    assert len(detail["payments"]) > 0 and detail["latest_run"] is None
    assert (await api.get("/renewals/nope")).status_code == 404

    r = await api.post("/renewals/pol_p01/runs")
    assert r.status_code == 202
    run = await wait_run(api, r.json()["id"])
    assert run["status"] == "succeeded"
    assert run["subject_name"] == detail["customer_name"]

    runs = (await api.get("/runs")).json()["items"]
    assert runs[0]["subject_name"] == detail["customer_name"]
    recs = (await api.get("/recommendations")).json()["items"]
    assert recs[0]["subject_name"] == detail["customer_name"]


async def test_single_run_refused_when_not_due(api) -> None:
    r = await api.post("/renewals/pol_p08/runs")  # cancelled
    assert r.status_code == 409
    assert r.json()["error"]["details"]["reason"] == "cancelled"
    r = await api.post("/renewals/pol_p17/runs")  # term life, nothing due
    assert r.status_code == 409
    assert r.json()["error"]["details"]["reason"] == "no_trigger"
