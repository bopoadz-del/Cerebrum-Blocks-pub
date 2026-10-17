"""First Domain Pack integration test: construction_ops (candidate).

Proves the pack loads through the real loader, its formulas execute
Decimal-deterministically, its rules refuse, its workflow gates, its
permissions deny by default, and its approval policy binds payloads.
The pack is CANDIDATE — the production-mode refusal is pinned too.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.reasoning_kernel import ReasoningStatus
from app.reasoning_kernel.approvals import ApprovalMatrixEngine
from app.reasoning_kernel.formulas import DeterministicFormulaExecutor, FormulaRegistry
from app.reasoning_kernel.loader import DomainPackLoader
from app.reasoning_kernel.ontology import OntologyRegistry, PermissionResolver
from app.reasoning_kernel.rules import DecisionTableEngine, RuleEngine
from app.reasoning_kernel.workflow import WorkflowEngine

PACK_PATH = Path(__file__).resolve().parents[2] / "domain_packs" / "construction_ops" / "pack.json"


def _retention_impl(i):
    return i["certified"] * i["rate"]


def _risk_impl(i):
    return int(i["probability"]) * int(i["impact"])


def _retention_oracle(**inputs):
    return Decimal(inputs["certified"]) * Decimal(inputs["rate"])


def _risk_oracle(**inputs):
    return int(inputs["probability"]) * int(inputs["impact"])


def _pack():
    return DomainPackLoader().load_path(str(PACK_PATH))


def _registry(pack):
    reg = FormulaRegistry()
    impls = {
        "con.retention": _retention_impl,
        "con.risk_score": _risk_impl,
    }
    for formula in pack.formulas:
        reg.register(formula, impls[formula.formula_id])
    return reg


def test_pack_loads_and_provenance_is_recorded():
    pack = _pack()
    assert pack.manifest.domain_id == "construction_ops"
    assert pack.manifest.donor_commit == "8535199"
    retention = pack.domain_approved_formulas
    assert retention == []  # candidate pack: nothing is domain_approved yet
    assert pack.formulas[0].provenance["donor_symbol"] == "calculate_payment"


def test_pack_formulas_execute_decimal():
    pack = _pack()
    executor = DeterministicFormulaExecutor(_registry(pack))
    out = executor.execute("con.retention", {"certified": "1000.00", "rate": "0.05"}, currency="SAR")
    assert out.status is ReasoningStatus.SUCCESS
    assert out.formulas_applied[0]["output"] == "50.00"
    risk = executor.execute("con.risk_score", {"probability": "4", "impact": "4"})
    assert risk.formulas_applied[0]["output"] == "16"


def test_production_mode_refuses_candidate_pack_formula():
    pack = _pack()
    executor = DeterministicFormulaExecutor(_registry(pack), production=True)
    out = executor.execute("con.retention", {"certified": "1000.00", "rate": "0.05"}, currency="SAR")
    assert out.status is ReasoningStatus.PERMISSION_DENIED
    assert "candidate" in out.explanation


def test_pack_rules_refuse_contract_violations():
    pack = _pack()
    engine = RuleEngine(pack.rules)
    out = engine.evaluate({"work_instruction": True, "dd_approved": False})
    assert out.status is ReasoningStatus.VALIDATION_ERROR
    assert out.rules_applied[0]["rule_id"] == "con.no_work_before_dd"
    ok = engine.evaluate({"work_instruction": True, "dd_approved": True})
    assert ok.status is ReasoningStatus.SUCCESS


def test_pack_risk_band_decision_table():
    pack = _pack()
    table = DecisionTableEngine(pack.decision_tables[0])
    red = table.evaluate({"score": 20})
    assert red.recommended_actions[0]["outcome"]["band"] == "RED"
    green = table.evaluate({"score": 3})
    assert green.recommended_actions[0]["outcome"]["band"] == "GREEN"


def test_pack_ncr_workflow_gates():
    pack = _pack()
    engine = WorkflowEngine(pack.workflows[0])
    engine.create("ncr-77")
    wrong_role = engine.transition("ncr-77", "under_review", actor="viewer", evidence={"photo": "p"})
    assert wrong_role.status is ReasoningStatus.PERMISSION_DENIED
    missing = engine.transition("ncr-77", "under_review", actor="qa_engineer")
    assert missing.status is ReasoningStatus.DEPENDENCY_REQUIRED
    ok = engine.transition("ncr-77", "under_review", actor="qa_engineer", evidence={"photo": "p"})
    assert ok.status is ReasoningStatus.SUCCESS


def test_pack_permissions_deny_by_default():
    pack = _pack()
    resolver = PermissionResolver(
        permissions=pack.permissions["role_permissions"],
        action_requirements=pack.permissions["action_requirements"],
    )
    denied = resolver.check("viewer", "con.certify_payment")
    assert denied.status is ReasoningStatus.PERMISSION_DENIED
    allowed = resolver.check("qa_engineer", "con.raise_ncr")
    assert allowed.status is ReasoningStatus.SUCCESS


def test_pack_approval_policy_binds_payload():
    pack = _pack()
    engine = ApprovalMatrixEngine(pack.approvals)
    payload = {"certificate_id": "PC-1", "amount": "500000"}
    token = engine.issue(
        "con.certify_payment",
        approver={"id": "pm-1", "role": "project_manager", "requester_id": "ce-1"},
        payload=payload,
    )
    out = engine.check(
        "con.certify_payment",
        requester={"id": "ce-1", "role": "controls_engineer"},
        payload=payload,
        approvals=[{"token": token, "requester_id": "ce-1"}],
    )
    assert out.status is ReasoningStatus.SUCCESS
    tampered = engine.check(
        "con.certify_payment",
        requester={"id": "ce-1", "role": "controls_engineer"},
        payload={"certificate_id": "PC-1", "amount": "999999"},
        approvals=[{"token": token, "requester_id": "ce-1"}],
    )
    assert tampered.status is ReasoningStatus.APPROVAL_REQUIRED


def test_pack_ontology_canonicalizes():
    pack = _pack()
    ontology = OntologyRegistry(pack.ontology)
    out = ontology.resolve("variation order")
    assert out.status is ReasoningStatus.SUCCESS
    assert out.facts[0]["canonical"] == "vo"
    unknown = ontology.resolve("teleporter")
    assert unknown.status is ReasoningStatus.UNSUPPORTED
