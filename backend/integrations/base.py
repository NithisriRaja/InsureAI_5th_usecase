"""Integration interfaces (the "approved connections"). Mocks read and write the CSV data
store; real adapters (CRM, policy admin, billing, messaging) can implement the same protocols
later without touching the agents."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from backend.db.models import Customer, Payment, Policy, Product


class CRM(Protocol):
    async def get_customer(self, customer_id: str) -> Customer | None: ...

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
        """Write a contact / status update to the customer's CRM record; returns its id."""
        ...


class PolicyAdmin(Protocol):
    async def get_policy(self, policy_id: str) -> Policy | None: ...
    async def get_product(self, code: str) -> Product | None: ...
    async def list_products(self, line: str | None = None) -> Sequence[Product]: ...
    async def mark_documents_received(self, policy_id: str, documents: list[str]) -> list[str]:
        """Clear received documents from the policy; returns those still outstanding."""
        ...


class Billing(Protocol):
    async def payments_for(self, policy_id: str) -> Sequence[Payment]: ...


class Messaging(Protocol):
    async def send(
        self,
        *,
        channel: str,
        recipient: str | None,
        body: str,
        subject: str | None,
        idempotency_key: str,
    ) -> str: ...
