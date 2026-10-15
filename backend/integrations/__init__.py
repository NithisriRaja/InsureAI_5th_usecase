"""Approved connections to the insurer's systems (CRM, policy admin, billing, messaging).

Only mocks exist in this POC; swap the factories below for real adapters.
"""

from __future__ import annotations

from backend.db.session import Database
from backend.integrations.base import CRM, PolicyAdmin
from backend.integrations.mocks import MockCRM, MockPolicyAdmin


def crm_for(db: Database) -> CRM:
    return MockCRM(db)


def policy_admin_for(db: Database) -> PolicyAdmin:
    return MockPolicyAdmin(db)
