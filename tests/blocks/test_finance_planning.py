"""Finance planning tests — ported behavior from <private-repo>."""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal

os.environ.setdefault("ENV", "test")

from app.blocks.finance_planning import FinancePlanningBlock


def _run(coro):
    return asyncio.run(coro)


def test_lock_requires_approval():
    b = FinancePlanningBlock()
    _run(b.process({"action": "create_budget", "tenant_id": "t1", "amount": "1000.00"}))
    r = _run(b.process({"action": "lock_budget", "budget_id": "b-1"}))
    assert r["status"] == "refused"
    assert "approved governance request" in r["error"]
    r2 = _run(b.process({"action": "lock_budget", "budget_id": "b-1", "approved": True}))
    assert r2["status"] == "ok"
    assert r2["result"]["budget"]["status"] == "locked"


def test_locked_budget_immutable_new_version():
    b = FinancePlanningBlock()
    _run(b.process({"action": "create_budget", "tenant_id": "t1", "amount": "1000.00"}))
    _run(b.process({"action": "lock_budget", "budget_id": "b-1", "approved": True}))
    r = _run(b.process({"action": "update_budget", "budget_id": "b-1", "amount": "2000.00"}))
    assert r["status"] == "ok"
    assert r["result"]["budget"]["version"] == 2
    assert r["result"]["budget"]["amount"] == "2000.00"
    # Original untouched.
    orig = _run(b.process({"action": "list_budgets"}))["result"]["budgets"][0]
    assert orig["amount"] == "1000.00" and orig["status"] == "locked"


def test_allocation_remainder_routes_to_first_member():
    b = FinancePlanningBlock()
    r = _run(b.process({"action": "run_allocation", "total_amount": "100.00", "members": ["m1", "m2", "m3"]}))
    assert r["status"] == "ok"
    results = r["result"]["results"]
    amounts = [Decimal(x["allocated_amount"]) for x in results]
    assert sum(amounts) == Decimal("100.00")  # exact total, never lost
    assert amounts[0] >= amounts[1]  # remainder routed to the first member


def test_allocation_without_members_refused():
    b = FinancePlanningBlock()
    r = _run(b.process({"action": "run_allocation", "total_amount": "100.00", "members": []}))
    assert r["status"] == "refused"


def test_draft_update_mutates_in_place():
    b = FinancePlanningBlock()
    _run(b.process({"action": "create_budget", "tenant_id": "t1", "amount": "500.00"}))
    r = _run(b.process({"action": "update_budget", "budget_id": "b-1", "amount": "600.00"}))
    assert r["result"]["budget"]["version"] == 1
    assert r["result"]["budget"]["amount"] == "600.00"
