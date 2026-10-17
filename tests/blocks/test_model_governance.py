"""Model governance â€” ported <private-repo> governance/service.py
AiUseCase / ModelGovernance register rules (in-process store)."""
from __future__ import annotations

import asyncio

from app.blocks.model_governance import ModelGovernanceBlock


def _run(coro):
    return asyncio.run(coro)


def _p(b, payload):
    return _run(b.process(payload))


def _mk(b, tenant="t1", risk="medium", status="draft"):
    return _p(b, {"action": "create_ai_use_case", "tenant_id": tenant,
                  "use_case_name": "invoice extraction", "model_name": "ocr-1",
                  "risk_tier": risk, "status": status})


def test_create_use_case_ok():
    b = ModelGovernanceBlock()
    r = _mk(b)
    assert r["status"] == "ok"
    assert r["result"]["use_case"]["risk_tier"] == "medium"
    assert r["result"]["use_case"]["status"] == "draft"


def test_invalid_risk_tier_fails_loud():
    b = ModelGovernanceBlock()
    r = _mk(b, risk="critical")
    assert r["status"] == "error"
    assert "Invalid risk_tier" in r["error"]
    assert r["detail"]["valid"] == ["high", "low", "medium"]


def test_invalid_use_case_status_fails_loud():
    b = ModelGovernanceBlock()
    r = _mk(b, status="archived")
    assert r["status"] == "error"
    assert "Invalid status" in r["error"]


def test_record_requires_existing_use_case():
    b = ModelGovernanceBlock()
    r = _p(b, {"action": "create_model_governance_record", "ai_use_case_id": "uc-404",
               "model_version": "v1"})
    assert r["status"] == "error"
    assert "AI use case not found" in r["error"]


def test_invalid_validation_status_fails_loud():
    b = ModelGovernanceBlock()
    _mk(b)
    r = _p(b, {"action": "create_model_governance_record", "ai_use_case_id": "uc-1",
               "model_version": "v1", "validation_status": "skipped"})
    assert r["status"] == "error"
    assert "Invalid validation_status" in r["error"]


def test_create_and_approve_record():
    b = ModelGovernanceBlock()
    _mk(b)
    r = _p(b, {"action": "create_model_governance_record", "ai_use_case_id": "uc-1",
               "model_version": "v1"})
    assert r["status"] == "ok"
    assert r["result"]["record"]["validation_status"] == "pending"
    rid = r["result"]["record"]["id"]
    r2 = _p(b, {"action": "approve_model", "record_id": rid, "notes": "passed eval"})
    assert r2["status"] == "ok"
    assert r2["result"]["record"]["validation_status"] == "approved"
    assert r2["result"]["record"]["validation_notes"] == "passed eval"


def test_approve_missing_record_fails_loud():
    b = ModelGovernanceBlock()
    r = _p(b, {"action": "approve_model", "record_id": "mg-404"})
    assert r["status"] == "error"
    assert "not found" in r["error"]


def test_tenant_scoped_listing():
    b = ModelGovernanceBlock()
    _mk(b, tenant="t1")
    _mk(b, tenant="t2", risk="high")
    r = _p(b, {"action": "list_ai_use_cases", "tenant_id": "t1"})
    assert r["status"] == "ok"
    assert r["result"]["count"] == 1
    assert r["result"]["use_cases"][0]["tenant_id"] == "t1"
    all_r = _p(b, {"action": "list_ai_use_cases"})
    assert all_r["result"]["count"] == 2


def test_unknown_action_is_error():
    b = ModelGovernanceBlock()
    assert _p(b, {"action": "nope"})["status"] == "error"
