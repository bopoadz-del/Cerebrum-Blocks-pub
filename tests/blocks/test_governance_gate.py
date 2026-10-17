"""Governance gate: fail-closed approval, ported from FinanceOps."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.governance_gate import GovernanceGateBlock


def _run(coro):
    return asyncio.run(coro)


def test_require_approved_refuses_without_request():
    b = GovernanceGateBlock()
    r = _run(b.process({"action": "require_approved", "tenant_id": "t1", "action_type": "budget_lock", "target_id": "b1"}))
    assert r["status"] == "refused"
    assert "approved request" in r["error"]


def test_full_approval_flow_then_allowed():
    b = GovernanceGateBlock()
    base = {"tenant_id": "t1", "action_type": "budget_lock", "target_id": "b1"}
    c = _run(b.process({"action": "create_request", **base, "requester_id": "alice"}))
    assert c["status"] == "ok"
    # self-approval refused
    s = _run(b.process({"action": "approve", **base, "approver_id": "alice"}))
    assert s["status"] == "error"
    assert "self-approval" in s["error"]
    # approver approves
    a = _run(b.process({"action": "approve", **base, "approver_id": "bob"}))
    assert a["status"] == "ok"
    # gate now passes
    r = _run(b.process({"action": "require_approved", **base}))
    assert r["status"] == "ok"
    assert r["result"]["approved"] is True


def test_pending_request_still_refuses():
    b = GovernanceGateBlock()
    base = {"tenant_id": "t1", "action_type": "scenario_publish", "target_id": "s1"}
    _run(b.process({"action": "create_request", **base, "requester_id": "alice"}))
    r = _run(b.process({"action": "require_approved", **base}))
    assert r["status"] == "refused"
    assert r["detail"]["status"] == "pending"


def test_duplicate_request_refused():
    b = GovernanceGateBlock()
    base = {"tenant_id": "t1", "action_type": "coa_activation", "target_id": "c1", "requester_id": "alice"}
    assert _run(b.process({"action": "create_request", **base}))["status"] == "ok"
    dup = _run(b.process({"action": "create_request", **base}))
    assert dup["status"] == "error"
