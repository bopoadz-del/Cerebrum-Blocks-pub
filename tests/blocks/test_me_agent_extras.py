"""Domain kit compiler + evidence-or-refuse tests (<private-repo> ports)."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.domain_kit_compiler import DomainKitCompilerBlock
from app.blocks.evidence_or_refuse import EvidenceOrRefuseBlock


def _run(coro):
    return asyncio.run(coro)


SHEET = {
    "domain": "hr",
    "tables": [
        {"name": "grades", "columns": [{"name": "grade"}, {"name": "band"}], "rows": [{"grade": "A", "band": "top"}]},
        {"name": "leave types", "columns": [{"name": "code"}], "rows": []},
    ],
}


def test_compiler_requires_domain():
    b = DomainKitCompilerBlock()
    r = _run(b.process({"action": "compile", "sheet": {"tables": []}}))
    assert r["status"] == "error"
    assert "domain" in r["error"]


def test_compiler_generates_lookup_blocks_with_failure_tests():
    b = DomainKitCompilerBlock()
    r = _run(b.process({"action": "compile", "sheet": SHEET}))
    assert r["status"] == "ok"
    assert r["result"]["domain"] == "hr"
    assert r["result"]["count"] == 2
    first = r["result"]["blocks"][0]
    assert first["block_id"] == "hr_grades_lookup"
    assert first["lookup_key"] == "grade"
    assert "must refuse" in first["failure_mode_test"]


def test_evidence_all_evidenced_allows():
    b = EvidenceOrRefuseBlock()
    r = _run(b.process({"action": "judge", "claims": [{"id": "c1", "evidence": ["d1#p1"]}, {"id": "c2", "evidence": ["d2#p3"]}]}))
    assert r["status"] == "ok"
    assert r["result"]["allowed"] is True


def test_unevidenced_claim_refused():
    b = EvidenceOrRefuseBlock()
    r = _run(b.process({"action": "judge", "claims": [{"id": "c1", "evidence": ["d1#p1"]}, {"id": "c2", "evidence": []}]}))
    assert r["status"] == "refused"
    assert "c2" in r["error"]


def test_judge_requires_claims():
    b = EvidenceOrRefuseBlock()
    r = _run(b.process({"action": "judge", "claims": []}))
    assert r["status"] == "error"
