"""Tests for the HKIA GN16/GL16 deterministic rules block."""

from pathlib import Path

import pytest

from app.blocks.hkia_gn16_rules import HKIAGN16RulesBlock


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def block():
    return HKIAGN16RulesBlock()


@pytest.fixture
def complete_payload():
    return {
        "text": (
            "Long term non-Class C life insurance policy evidence. Product brochure is bilingual "
            "and plain language with key risk, key exclusion, fees, charges, surrender penalty, "
            "and cooling-off period information. Financial Needs Analysis FNA completed with "
            "knowledge and experience, needs, priorities, circumstances, affordability, and "
            "premium payment horizon. Commission plan is earned basis only with no indemnity "
            "commission. Clawback covers fraud, money laundering, and mis-selling. Conflict of "
            "interest disclosure, informed consent, and ongoing monitoring mechanism are recorded. "
            "Participating policy non-guaranteed benefits receive annual statement and projection "
            "updates. Policy loan terms, interest rate, notification, account statement, and loan "
            "balance controls are disclosed. Vulnerable customer post-sale confirmation call was "
            "audio-recorded within five working days. Confirmation letter, email SMS alert, control "
            "report, and unsuccessful call monitoring are retained."
        ),
        "customer_age": 68,
        "vulnerable_customer": True,
    }


@pytest.mark.asyncio
async def test_evaluate_returns_structured_findings(block):
    payload = {
        "text": (
            "Long term non-Class C life insurance recommendation. The intermediary compensation "
            "schedule permits indemnity commission and advance commission. Customer is age 70 "
            "with no regular income. Product risks are discussed."
        ),
        "customer_age": 70,
        "regular_income": False,
        "advice_given": True,
    }

    result = await block.execute(payload, {"operation": "evaluate"})

    assert result["block"] == "hkia_gn16_rules"
    assert result["status"] == "success"
    evaluation = result["result"]
    assert evaluation["operation"] == "evaluate"
    assert evaluation["live_filing_submission"] is False
    assert evaluation["compliant"] is False

    rule_ids = {finding["rule_id"] for finding in evaluation["findings"]}
    assert "GN16-REM-001" in rule_ids
    assert "GN16-VULN-001" in rule_ids

    for finding in evaluation["findings"]:
        assert finding["severity"]
        assert finding["rule_id"].startswith("GN16-")
        assert finding["citation"].startswith("HKIA")
        assert finding["remediation"]


@pytest.mark.asyncio
async def test_complete_payload_has_no_findings(block, complete_payload):
    result = await block.execute(complete_payload, {"operation": "evaluate"})

    evaluation = result["result"]
    assert result["status"] == "success"
    assert evaluation["compliant"] is True
    assert evaluation["findings"] == []
    assert "GN16-SUIT-001" in evaluation["rules_evaluated"]
    assert "GN16-REM-001" in evaluation["rules_evaluated"]


@pytest.mark.asyncio
async def test_list_rules_and_explain_finding(block):
    listed = await block.execute({}, {"operation": "list_rules"})
    assert listed["status"] == "success"
    assert listed["result"]["rule_count"] >= 10
    assert {rule["rule_id"] for rule in listed["result"]["rules"]} >= {
        "GN16-SUIT-001",
        "GN16-VULN-001",
        "GN16-REM-001",
    }

    explained = await block.execute({}, {"operation": "explain_finding", "rule_id": "GN16-SUIT-001"})
    explanation = explained["result"]
    assert explanation["status"] == "success"
    assert explanation["rule_id"] == "GN16-SUIT-001"
    assert "Suitability" in explanation["title"]
    assert explanation["remediation"]


@pytest.mark.asyncio
async def test_build_audit_package(block, complete_payload):
    result = await block.execute(complete_payload, {"operation": "build_audit_package"})

    package = result["result"]
    assert result["status"] == "success"
    assert package["operation"] == "build_audit_package"
    assert package["package_type"] == "hkia_gn16_layer1_compliance_audit"
    assert package["live_filing_submission"] is False
    assert len(package["evidence_digest_sha256"]) == 64
    assert package["corpus_references"]
    assert package["evaluation"]["operation"] == "evaluate"


@pytest.mark.asyncio
async def test_audit_digest_includes_structured_fields(block, complete_payload):
    first = await block.execute(complete_payload, {"operation": "build_audit_package"})
    altered = dict(complete_payload)
    altered["customer_age"] = 42
    second = await block.execute(altered, {"operation": "build_audit_package"})

    assert first["result"]["evidence_digest_sha256"] != second["result"]["evidence_digest_sha256"]


@pytest.mark.asyncio
async def test_prohibited_terms_require_local_negation(block):
    payload = {
        "text": (
            "Intermediary compensation schedule. Advance commission is offered for new writers. "
            "Separately, the product brochure states that unsolicited cold calling is prohibited."
        ),
        "commission_arrangement": True,
    }

    result = await block.execute(payload, {"operation": "evaluate"})
    evaluation = result["result"]
    rule_ids = {finding["rule_id"] for finding in evaluation["findings"]}
    assert "GN16-REM-001" in rule_ids


def test_bundle_copy_and_knowledge_assets_exist():
    root_block = ROOT / "app" / "blocks" / "hkia_gn16_rules.py"
    bundle_block = ROOT / "block_store" / "kits" / "insurance" / "bundle" / "app" / "blocks" / "hkia_gn16_rules.py"
    corpus = ROOT / "block_store" / "kits" / "insurance" / "bundle" / "app" / "knowledge" / "hkia_gn16_corpus.json"
    ruleset = ROOT / "block_store" / "kits" / "insurance" / "bundle" / "app" / "data" / "gn16_ruleset.json"
    registry = ROOT / "block_registry" / "hkia_gn16_rules" / "block.json"

    assert bundle_block.read_text(encoding="utf-8") == root_block.read_text(encoding="utf-8")
    assert corpus.exists()
    assert ruleset.exists()
    assert registry.exists()
