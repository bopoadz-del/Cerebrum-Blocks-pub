"""<client> ports: verified outcome learning + hat framework."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.hat_framework import HatFrameworkBlock
from app.blocks.verified_outcome_learning import VerifiedOutcomeLearningBlock


def _run(coro):
    return asyncio.run(coro)


def test_learning_unknown_module_refused():
    b = VerifiedOutcomeLearningBlock()
    r = _run(b.process({"action": "validate", "module": "nope", "payload": {}}))
    assert r["status"] == "error"
    assert "unknown_module" in r["error"]


def test_learning_payload_validation():
    b = VerifiedOutcomeLearningBlock()
    r = _run(b.process({"action": "validate", "module": "demand_reorder", "payload": {}}))
    assert r["result"]["valid"] is False
    assert "sku" in r["result"]["missing"]


def test_unverified_event_stored_not_applied():
    b = VerifiedOutcomeLearningBlock()
    base = {"tenant_id": "t1", "project_id": "p1", "module": "demand_reorder", "payload": {"sku": "s1", "lead_time_days": 3}, "verified_by": "u1", "deduplication_key": "k1"}
    r = _run(b.process({"action": "record", **base, "verification_status": "pending"}))
    assert r["status"] == "ok"
    assert r["result"]["applied"] is False
    prof = _run(b.process({"action": "profile", "tenant_id": "t1"}))
    assert prof["result"]["profile"] == {}


def test_verified_event_applied():
    b = VerifiedOutcomeLearningBlock()
    base = {"tenant_id": "t1", "project_id": "p1", "module": "demand_reorder", "payload": {"sku": "s1", "lead_time_days": 3}, "verified_by": "u1", "deduplication_key": "k1"}
    r = _run(b.process({"action": "record", **base, "verification_status": "verified"}))
    assert r["result"]["applied"] is True
    prof = _run(b.process({"action": "profile", "tenant_id": "t1"}))
    assert prof["result"]["profile"]["last_event_id"] == r["result"]["event"]["id"]


def test_hat_requires_base_agent_id():
    b = HatFrameworkBlock()
    r = _run(b.process({"action": "register", "manifest": {"id": "h1", "kind": "hat"}}))
    assert r["status"] == "refused"


def test_hat_compose_overlays_base():
    b = HatFrameworkBlock()
    _run(b.process({"action": "register", "manifest": {"id": "planner", "kind": "base", "name": "Planner", "policies": ["p1"]}}))
    _run(b.process({"action": "register", "manifest": {"id": "safety_hat", "kind": "hat", "base_agent_id": "planner", "policies": ["safety-kpi"]}}))
    r = _run(b.process({"action": "compose", "hat_id": "safety_hat"}))
    assert r["status"] == "ok"
    assert r["result"]["composed"]["hat"] == "safety_hat"
    assert r["result"]["composed"]["policies"] == ["p1", "safety-kpi"]


def test_hat_compose_missing_base_refused():
    b = HatFrameworkBlock()
    _run(b.process({"action": "register", "manifest": {"id": "orphan_hat", "kind": "hat", "base_agent_id": "ghost"}}))
    r = _run(b.process({"action": "compose", "hat_id": "orphan_hat"}))
    assert r["status"] == "refused"
