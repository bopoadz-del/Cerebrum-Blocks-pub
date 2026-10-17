"""Approval rules tests - ported behavior from <private-repo> approval.py."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.approval_rules import ApprovalRulesBlock


def _run(coro):
    return asyncio.run(coro)


EXTRACTED = [
    {
        "rule_id": "SPEC-GAS-LV-400",
        "system_a": "gas_main",
        "system_b": "electrical_lv",
        "min_gap_mm": 400,
        "axis": "any",
        "precedence": "project_spec",
        "source_doc": "spec.pdf",
        "source_clause": "3.1",
        "quote": "Gas mains shall be separated from LV cables by not less than 400 mm.",
    },
    {
        "rule_id": "SPEC-DUCT-CABLE-100",
        "system_a": "duct",
        "system_b": "cable_tray",
        "min_gap_mm": 100,
        "source": {"doc": "spec.pdf", "clause": "4.2", "text_hash": "abc"},
    },
]


def _ingest(b, project="p1", doc="spec.pdf"):
    return _run(b.process({"action": "ingest", "project_id": project, "source_doc": doc, "extracted": EXTRACTED}))


def test_candidates_arrive_inert():
    b = ApprovalRulesBlock()
    r = _ingest(b)
    assert r["status"] == "ok"
    assert all(c["status"] == "pending_approval" for c in r["result"]["candidates"])
    approved = _run(b.process({"action": "approved", "project_id": "p1", "source_doc": "spec.pdf"}))
    assert approved["result"]["rules"] == []


def test_named_reviewer_approves_one_by_id():
    b = ApprovalRulesBlock()
    _ingest(b)
    r = _run(b.process({
        "action": "decide", "project_id": "p1", "source_doc": "spec.pdf",
        "rule_id": "SPEC-GAS-LV-400", "approve": True, "reviewer": "an engineer",
        "note": "checked against the drawing",
    }))
    assert r["status"] == "ok"
    assert r["result"]["status"] == "approved"
    assert r["result"]["decided_by"] == "an engineer"
    # Only the one rule reached the kit loader shape.
    approved = _run(b.process({"action": "approved", "project_id": "p1", "source_doc": "spec.pdf"}))
    assert [x["rule_id"] for x in approved["result"]["rules"]] == ["SPEC-GAS-LV-400"]
    assert approved["result"]["rules"][0]["min_gap_mm"] == 400.0
    assert approved["result"]["rules"][0]["source"]["clause"] == "3.1"


def test_source_fallback_when_payload_has_no_source_key():
    b = ApprovalRulesBlock()
    _ingest(b)
    _run(b.process({
        "action": "decide", "project_id": "p1", "source_doc": "spec.pdf",
        "rule_id": "SPEC-DUCT-CABLE-100", "approve": True, "reviewer": "engineer-2",
    }))
    approved = _run(b.process({"action": "approved", "project_id": "p1", "source_doc": "spec.pdf"}))
    assert approved["result"]["rules"][0]["source"] == {"doc": "spec.pdf", "clause": "4.2", "text_hash": "abc"}


def test_anonymous_approval_is_refused():
    b = ApprovalRulesBlock()
    _ingest(b)
    r = _run(b.process({
        "action": "decide", "project_id": "p1", "source_doc": "spec.pdf",
        "rule_id": "SPEC-GAS-LV-400", "approve": True, "reviewer": "   ",
    }))
    assert r["status"] == "refused"
    assert "name the person" in r["error"]
    # Nothing was applied and no ledger row was written.
    approved = _run(b.process({"action": "approved", "project_id": "p1", "source_doc": "spec.pdf"}))
    assert approved["result"]["rules"] == []
    ledger = _run(b.process({"action": "ledger"}))
    assert ledger["result"]["count"] == 0


def test_deciding_an_unknown_rule_is_refused():
    b = ApprovalRulesBlock()
    _ingest(b)
    r = _run(b.process({
        "action": "decide", "project_id": "p1", "source_doc": "spec.pdf",
        "rule_id": "SPEC-NOT-REAL", "approve": True, "reviewer": "an engineer",
    }))
    assert r["status"] == "refused"
    assert "SPEC-NOT-REAL" in r["error"]


def test_deciding_without_an_ingested_set_is_refused():
    b = ApprovalRulesBlock()
    r = _run(b.process({
        "action": "decide", "project_id": "p1", "source_doc": "spec.pdf",
        "rule_id": "SPEC-GAS-LV-400", "approve": True, "reviewer": "an engineer",
    }))
    assert r["status"] == "refused"


def test_rejection_stays_out_of_approved_rules_and_is_ledgered():
    b = ApprovalRulesBlock()
    _ingest(b)
    r = _run(b.process({
        "action": "decide", "project_id": "p1", "source_doc": "spec.pdf",
        "rule_id": "SPEC-GAS-LV-400", "approve": False, "reviewer": "engineer-2",
    }))
    assert r["result"]["status"] == "rejected"
    approved = _run(b.process({"action": "approved", "project_id": "p1", "source_doc": "spec.pdf"}))
    assert approved["result"]["rules"] == []
    ledger = _run(b.process({"action": "ledger"}))
    row = ledger["result"]["ledger"][0]
    assert row["from_state"] == "pending_approval"
    assert row["to_state"] == "rejected"
    assert row["actor"] == "engineer-2"
    assert row["payload"]["clause"] == "3.1"


def test_ledger_carries_who_when_and_against_what_text():
    b = ApprovalRulesBlock()
    _ingest(b)
    _run(b.process({
        "action": "decide", "project_id": "p1", "source_doc": "spec.pdf",
        "rule_id": "SPEC-GAS-LV-400", "approve": True, "reviewer": "an engineer",
    }))
    ledger = _run(b.process({"action": "ledger"}))
    assert ledger["result"]["count"] == 1
    row = ledger["result"]["ledger"][0]
    assert row["actor"] == "an engineer"
    assert row["payload"]["min_gap_mm"] == 400
    assert row["payload"]["rule_id"] == "SPEC-GAS-LV-400"


def test_no_batch_approval_exists():
    b = ApprovalRulesBlock()
    _ingest(b)
    r = _run(b.process({"action": "approve_all", "project_id": "p1"}))
    assert r["status"] == "error"
    assert "approve_all" not in str(r.get("result"))


def test_ingest_without_source_doc_is_refused():
    b = ApprovalRulesBlock()
    r = _run(b.process({"action": "ingest", "project_id": "p1", "extracted": EXTRACTED}))
    assert r["status"] == "refused"


def test_unknown_action_is_error():
    b = ApprovalRulesBlock()
    r = _run(b.process({"action": "nonsense"}))
    assert r["status"] == "error"
    assert r["block_id"] == "approval_rules"
