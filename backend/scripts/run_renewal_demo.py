"""Renewal demo against a running API: scan -> wait -> show -> approve/edit/reject.

python -m backend.scripts.run_renewal_demo
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _demo_client import client, login, show, wait_runs


def main() -> None:
    c = client()
    batch = c.post("/renewals/scan").json()
    print(f"\nScan {batch['id']}: queued {len(batch['run_ids'])}, skipped:")
    for s in batch["skipped"]:
        print(f"  - {s['policy_number']}: {s['reason']}")
    wait_runs(c, batch["run_ids"])

    queue = c.get("/recommendations", params={"queue": "retention", "limit": 100}).json()
    for rec in queue["items"]:
        show(c.get(f"/recommendations/{rec['id']}").json())

    h = login(c, "Demo Retention", "retention")
    offers = [r for r in queue["items"] if r["action"] == "retention_offer"]
    others = [r for r in queue["items"] if r["action"] != "retention_offer"]
    if offers:
        rec = offers[0]
        bad = c.post(
            f"/approvals/{rec['id']}/edit", headers=h, json={"edits": {"discount_pct": 50}}
        )
        print(
            f"\nEdit to 50% discount (expected 422): {bad.status_code} "
            f"{[d['rule'] for d in bad.json()['error'].get('details') or []]}"
        )
        ok = c.post(
            f"/approvals/{rec['id']}/approve", headers=h, json={"expected_version": rec["version"]}
        )
        print(f"Approve offer {rec['id']}: {ok.status_code} {ok.json()}")
    if others:
        rec = others[0]
        r = c.post(
            f"/approvals/{rec['id']}/reject",
            headers=h,
            json={"reason": "Customer already contacted by phone"},
        )
        print(f"Reject {rec['id']}: {r.status_code} {r.json()}")

    time.sleep(2.5)  # let the outbox deliver
    for m in c.get("/messages").json()["items"]:
        print(
            f"\nMessage {m['id']} [{m['channel']} -> {m['recipient']}] {m['status']}\n{m['body']}"
        )
    print("\nStats:", c.get("/stats").json())


if __name__ == "__main__":
    main()
