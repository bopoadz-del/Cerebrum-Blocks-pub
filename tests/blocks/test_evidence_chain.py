"""Evidence chain: SHA-256 chain + full-walk verifier, ported from FinanceOps."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.evidence_chain import EvidenceChainBlock


def _run(coro):
    return asyncio.run(coro)


def _record(b, i=0, action_type="journal_post"):
    return _run(b.process({
        "action": "record",
        "tenant_id": "t1",
        "action_type": action_type,
        "principal_id": f"u{i}",
        "payload": {"amount": 100 + i},
        "result": {"posted": True},
    }))


def test_record_and_verify_full_walk():
    b = EvidenceChainBlock()
    for i in range(3):
        r = _record(b, i)
        assert r["status"] == "ok"
    v = _run(b.process({"action": "verify"}))
    assert v["status"] == "ok"
    assert v["result"]["intact"] is True
    assert v["result"]["walked"] == 3


def test_tampered_record_breaks_the_walk():
    b = EvidenceChainBlock()
    _record(b, 0)
    _record(b, 1)
    _record(b, 2)
    # Tamper with the middle record's payload hash.
    b._chain[1]["payload_hash"] = "0" * 64
    v = _run(b.process({"action": "verify"}))
    assert v["status"] == "refused"
    assert v["detail"]["chain_broken"] is True
    assert v["detail"]["id"] == b._chain[1]["id"]


def test_broken_previous_link_is_detected():
    b = EvidenceChainBlock()
    _record(b, 0)
    _record(b, 1)
    b._chain[1]["previous_hash"] = "0" * 64
    v = _run(b.process({"action": "verify"}))
    assert v["status"] == "refused"
    assert "chain broken" in v["error"]


def test_get_latest():
    b = EvidenceChainBlock()
    assert _run(b.process({"action": "get_latest"}))["result"]["record"] is None
    _record(b, 0)
    latest = _run(b.process({"action": "get_latest"}))
    assert latest["result"]["record"]["id"] == b._chain[-1]["id"]
