"""Tiny helpers shared by the demo scripts (talk to a running API)."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import httpx

BASE = os.environ.get("API_URL", "http://127.0.0.1:8000")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # LLM text may contain any char


def client() -> httpx.Client:
    c = httpx.Client(base_url=BASE, timeout=30)
    try:
        h = c.get("/health").json()
    except httpx.HTTPError:
        sys.exit(f"API not reachable at {BASE}. Start it: python -m uvicorn main:app")
    print(
        f"API ok | provider={h['llm']['provider']} model={h['llm']['model']} "
        f"key={'yes' if h['llm']['key_configured'] else 'NO'} | as_of={h['as_of']}"
    )
    return c


def login(c: httpx.Client, name: str, role: str) -> dict[str, str]:
    r = c.post("/sessions", json={"name": name, "role": role})
    r.raise_for_status()
    return {"X-Session-Id": r.json()["session_id"]}


def wait_runs(c: httpx.Client, run_ids: list[str], timeout_s: float = 600) -> list[dict]:
    deadline = time.time() + timeout_s
    pending = set(run_ids)
    done: dict[str, dict] = {}
    while pending and time.time() < deadline:
        for rid in list(pending):
            run = c.get(f"/runs/{rid}").json()
            if run["status"] in ("succeeded", "failed", "skipped"):
                pending.discard(rid)
                done[rid] = run
                mark = {"succeeded": "OK ", "failed": "ERR", "skipped": "SKP"}[run["status"]]
                extra = run["error_code"] or run.get("recommendation_id") or ""
                print(f"  [{mark}] {run['subject_id']:<10} {extra}")
        if pending:
            time.sleep(1.5)
    if pending:
        print(f"  still running after {timeout_s}s: {sorted(pending)}")
    return list(done.values())


def show(rec: dict[str, Any]) -> None:
    print(
        f"\n== {rec['id']}  [{rec['queue']}/{rec['priority']}]  {rec['action']}"
        f"  band={rec['band']} conf={rec['confidence']} review={rec['needs_review']}"
    )
    print(f"   subject: {json.dumps(rec.get('subject', {}), default=str)[:160]}")
    print(f"   why: {rec['explanation']}")
    failed = [r["id"] for r in rec.get("rule_results", []) if not r["passed"]]
    if failed:
        print(f"   rules not passed: {failed}")
    if rec.get("review_reasons"):
        print(f"   review: {rec['review_reasons']}")
    if rec.get("offer"):
        print(f"   offer: {rec['offer']}")
    if rec.get("draft_message"):
        print(f"   draft ({rec['channel']}): {rec['draft_message'][:240]}")
    print(f"   fairness: {rec.get('fairness')}")
