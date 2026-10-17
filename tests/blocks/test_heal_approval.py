"""Heal approval tests — ported behavior from <private-repo>."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.heal_approval import HealApprovalBlock, heal_approval_digest


def _run(coro):
    return asyncio.run(coro)


def test_digest_is_deterministic():
    assert heal_approval_digest(tenant_id="t1", action_id="a1", principal_id="u1") == heal_approval_digest(tenant_id="t1", action_id="a1", principal_id="u1")
    assert heal_approval_digest(tenant_id="t1", action_id="a1", principal_id="u2") != heal_approval_digest(tenant_id="t1", action_id="a1", principal_id="u1")


def test_create_consume_once():
    b = HealApprovalBlock()
    c = _run(b.process({"action": "create", "tenant_id": "t1", "principal_id": "u1", "action_id": "heal-x"}))
    assert c["status"] == "ok"
    aid = c["result"]["approval"]["approval_id"]
    ok = _run(b.process({"action": "consume", "approval_id": aid, "tenant_id": "t1", "principal_id": "u1", "action_id": "heal-x"}))
    assert ok["status"] == "ok"
    replay = _run(b.process({"action": "consume", "approval_id": aid, "tenant_id": "t1", "principal_id": "u1", "action_id": "heal-x"}))
    assert replay["status"] == "refused"
    assert "replay" in replay["error"]


def test_field_mismatch_refused():
    b = HealApprovalBlock()
    c = _run(b.process({"action": "create", "tenant_id": "t1", "principal_id": "u1", "action_id": "heal-x"}))
    aid = c["result"]["approval"]["approval_id"]
    r = _run(b.process({"action": "consume", "approval_id": aid, "tenant_id": "t2", "principal_id": "u1", "action_id": "heal-x"}))
    assert r["status"] == "refused"


def test_expiry_refused():
    b = HealApprovalBlock()
    c = _run(b.process({"action": "create", "tenant_id": "t1", "principal_id": "u1", "action_id": "heal-x", "ttl_seconds": -1}))
    aid = c["result"]["approval"]["approval_id"]
    r = _run(b.process({"action": "consume", "approval_id": aid, "tenant_id": "t1", "principal_id": "u1", "action_id": "heal-x"}))
    assert r["status"] == "refused"
    assert "expired" in r["error"]
