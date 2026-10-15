from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from backend.db.models import Customer, Policy, Run
from backend.db.session import Database, IntegrityError
from backend.utils.clock import today, utcnow


async def test_clock_uses_as_of_date() -> None:
    assert today().isoformat() == "2026-10-13"


async def test_seed_small_counts(seeded_db: Database) -> None:
    async with seeded_db.session() as s:
        assert len(s.all(Policy)) == 18
        assert len(s.all(Customer)) == 18
        # The lifecycle monitor's first pass stored each policy's next event.
        p13 = await s.get(Policy, "pol_p13")
        assert p13 is not None and p13.next_event_type == "premium_missed"
        assert p13.policy_number.startswith("LIF-")


async def test_only_one_active_run_per_subject(db: Database) -> None:
    def run(run_id: str, status: str = "queued") -> Run:
        return Run(
            id=run_id,
            use_case="renewal",
            subject_type="policy",
            subject_id="pol_x",
            cycle_key="pol_x:upcoming_expiry:2026-11-01",
            status=status,
        )

    async with db.session() as s:
        s.add(run("run_1"))
    with pytest.raises(IntegrityError):
        async with db.session() as s:
            s.add(run("run_2"))
    # Finished runs don't block a new one.
    async with db.session() as s:
        r1 = await s.get(Run, "run_1")
        assert r1 is not None
        r1.status = "succeeded"
    async with db.session() as s:
        s.add(run("run_3"))


async def test_timestamps_roundtrip_as_utc(db: Database) -> None:
    async with db.session() as s:
        s.add(
            Run(
                id="run_t",
                use_case="renewal",
                subject_type="policy",
                subject_id="p",
                cycle_key="p:1",
            )
        )
    async with db.session() as s:
        r = await s.get(Run, "run_t")
        assert r is not None and r.created_at.tzinfo is not None


async def test_naive_datetime_rejected(db: Database) -> None:
    with pytest.raises(ValueError, match="naive datetime"):
        async with db.session() as s:
            s.add(
                Run(
                    id="run_n",
                    use_case="renewal",
                    subject_type="policy",
                    subject_id="p",
                    cycle_key="p:1",
                    started_at=datetime(2026, 1, 1),
                )
            )
            await s.flush()
    assert utcnow().tzinfo is not None


async def test_csv_round_trip(seeded_db: Database, tmp_path) -> None:
    """Every table survives a save + reload through CSV with types intact."""
    await seeded_db.save()
    assert (seeded_db.data_dir / "policies.csv").exists()
    again = Database(seeded_db.data_dir)
    await again.create_all()
    try:
        async with seeded_db.session() as s1, again.session() as s2:
            for model in (Policy, Customer, Run):
                assert len(s1.all(model)) == len(s2.all(model))
            a, b = await s1.get(Policy, "pol_p13"), await s2.get(Policy, "pol_p13")
            for f in dataclasses.fields(Policy):
                assert getattr(a, f.name) == getattr(b, f.name), f.name
    finally:
        await again.dispose()


async def test_commit_writes_changed_table_to_csv(db: Database) -> None:
    async with db.session() as s:
        s.add(
            Run(
                id="run_c",
                use_case="renewal",
                subject_type="policy",
                subject_id="p",
                cycle_key="p:1",
            )
        )
    assert not (db.data_dir / "runs.csv").exists()  # runs are memory-only
    async with db.session() as s:
        s.add(Customer(id="cust_c", first_name="A", last_name="B"))
    text = (db.data_dir / "customers.csv").read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("id,") and "cust_c" in text
    assert not (db.data_dir / "policies.csv").exists()  # untouched tables are not written


async def test_memory_only_tables_write_no_csv(db: Database) -> None:
    from backend.db.models import Batch, Session, User

    async with db.session() as s:
        s.add(User(id="usr_m", name="M", name_key="m", role="admin"))
        s.add(Batch(id="bat_m", kind="renewal_scan"))
        s.add(
            Session(id="ses_m", user_id="usr_m", expires_at=datetime(2030, 1, 1, tzinfo=UTC))
        )
    for name in ("users", "batches", "sessions", "llm_calls"):
        assert not (db.data_dir / f"{name}.csv").exists(), name
    async with db.session() as s:  # still usable while the app runs
        assert await s.get(Batch, "bat_m") is not None
