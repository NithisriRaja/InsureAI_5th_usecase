"""Mock integrations backed by the CSV data store. Each call is its own unit of work."""

from __future__ import annotations

from collections.abc import Sequence

from backend.db.models import CrmActivity, Customer, Payment, Policy, Product
from backend.db.repositories import policies as policies_repo
from backend.db.session import Database
from backend.utils.ids import new_id


class MockCRM:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_customer(self, customer_id: str) -> Customer | None:
        async with self.db.session() as s:
            return await policies_repo.get_customer(s, customer_id)

    async def log_activity(
        self,
        *,
        kind: str,
        summary: str,
        policy_id: str | None = None,
        recommendation_id: str | None = None,
        channel: str | None = None,
        actor: str = "system",
    ) -> str:
        async with self.db.session() as s:
            policy = await policies_repo.get(s, policy_id) if policy_id else None
            row = CrmActivity(
                id=new_id("crm"),
                customer_id=policy.customer_id if policy else None,
                policy_id=policy_id,
                recommendation_id=recommendation_id,
                kind=kind,
                channel=channel,
                summary=summary[:500],
                actor=actor,
            )
            s.add(row)
        return row.id


class MockPolicyAdmin:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_policy(self, policy_id: str) -> Policy | None:
        async with self.db.session() as s:
            return await policies_repo.get(s, policy_id)

    async def get_product(self, code: str) -> Product | None:
        async with self.db.session() as s:
            return await policies_repo.get_product(s, code)

    async def list_products(self, line: str | None = None) -> Sequence[Product]:
        async with self.db.session() as s:
            return await policies_repo.list_products(s, line=line)


    async def mark_documents_received(self, policy_id: str, documents: list[str]) -> list[str]:
        async with self.db.session() as s:
            policy = await policies_repo.get(s, policy_id)
            if policy is None:
                raise LookupError(f"policy {policy_id} not found")
            received = set(documents)
            policy.docs_outstanding = [d for d in policy.docs_outstanding if d not in received]
            return list(policy.docs_outstanding)


class MockBilling:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def payments_for(self, policy_id: str) -> Sequence[Payment]:
        async with self.db.session() as s:
            return await policies_repo.payments_for(s, policy_id)
