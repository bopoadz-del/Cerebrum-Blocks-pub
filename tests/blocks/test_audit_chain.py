"""Behavior tests for the audit_chain block (FinanceOps port).

Every assertion exercises tamper evidence: the full walk must catch a
tampered payload digest, a broken previous-hash link, and a doctored
chain hash — by name, per record.
"""

from __future__ import annotations

import pytest

from app.blocks.audit_chain import AuditChainBlock, _LEDGERS, _hash_blob


@pytest.fixture()
def chain():
    return AuditChainBlock()


@pytest.fixture(autouse=True)
def _fresh_ledger():
    _LEDGERS.clear()
    yield
    _LEDGERS.clear()


async def _call(chain, action, tenant="t1", **data):
    envelope = await chain.execute({**data, "tenant_id": tenant}, {"action": action})
    return envelope["result"]


async def _record(chain, exec_id="e-1", payload=None, result=None):
    return await _call(
        chain, "record_evidence",
        action_execution_id=exec_id, action_type="journal_post",
        principal_id="u1", payload=payload or {"amount": 10},
        result=result or {"ok": True},
    )


@pytest.mark.asyncio
async def test_clean_chain_verifies(chain):
    await _record(chain, "e-1")
    await _record(chain, "e-2", payload={"amount": 20})
    verdict = await _call(chain, "verify_chain")
    assert verdict["status"] == "success"
    assert verdict["verified"] is True
    assert verdict["records_walked"] == 2
    assert verdict["violations"] == []


@pytest.mark.asyncio
async def test_tampered_payload_digest_is_detected(chain):
    await _record(chain, "e-1")
    await _record(chain, "e-2", payload={"amount": 20})
    ledger = _LEDGERS["t1"]
    ledger["evidence"][1]["payload_hash"] = _hash_blob({"amount": 999999})
    verdict = await _call(chain, "verify_chain")
    assert verdict["verified"] is False
    assert any("chain_hash mismatch" in v["error"] for v in verdict["violations"])
    assert any(v["record"] == ledger["evidence"][1]["id"] for v in verdict["violations"])


@pytest.mark.asyncio
async def test_broken_previous_link_is_detected(chain):
    await _record(chain, "e-1")
    await _record(chain, "e-2")
    ledger = _LEDGERS["t1"]
    ledger["evidence"][1]["previous_hash"] = "0" * 64
    verdict = await _call(chain, "verify_chain")
    assert verdict["verified"] is False
    assert any("previous_hash linkage broken" in v["error"] for v in verdict["violations"])


@pytest.mark.asyncio
async def test_doctored_chain_hash_is_detected(chain):
    await _record(chain, "e-1")
    ledger = _LEDGERS["t1"]
    ledger["evidence"][0]["chain_hash"] = "f" * 64
    verdict = await _call(chain, "verify_chain")
    assert verdict["verified"] is False
    assert any("chain_hash mismatch" in v["error"] for v in verdict["violations"])


@pytest.mark.asyncio
async def test_missing_required_fields_are_refused(chain):
    result = await _call(chain, "record_evidence")
    assert result["status"] == "error"
    assert "missing" in result["error"]


@pytest.mark.asyncio
async def test_log_action_and_filters(chain):
    await _call(chain, "log_action", principal_id="u1", action_name="export", resource_type="report", resource_id="r-1", status="ok")
    envelope = await chain.execute(
        {"tenant_id": "t1", "action": "export"},
        {"action": "list_logs"},
    )
    logs = envelope["result"]
    assert logs["status"] == "success"
    assert len(logs["logs"]) == 1
    assert logs["logs"][0]["resource_id"] == "r-1"
