"""Reasoning Kernel — second slice behavior tests.

Loader/validator, evidence/authority/refusal/assumptions, provenance
chain, explanation composer, oracle runner, version pinning, planner +
action-plan validator. Each engine proven both ways.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.reasoning_kernel import ReasoningResult, ReasoningStatus
from app.reasoning_kernel.evidence import (
    AssumptionRegistry,
    AuthorityResolver,
    EvidenceRequirementEngine,
    RefusalEngine,
)
from app.reasoning_kernel.loader import DomainPackLoader, PackLoadError
from app.reasoning_kernel.oracles import ExplanationComposer, VerificationOracleRunner
from app.reasoning_kernel.planner import ActionPlanValidator, DomainPackVersionManager, ReasoningPlanner
from app.reasoning_kernel.provenance import ConflictDetector, ProvenanceRecorder
from app.reasoning_kernel.schemas import (
    Certification,
    FormulaSpec,
    PackManifest,
    RuleSpec,
    WorkflowSpec,
)


def _pack_dict(**overrides):
    raw = {
        "manifest": {
            "domain_id": "construction_ops",
            "version": "1.0.0",
            "name": "Construction Ops",
            "certification": "technically_verified",
        },
        "formulas": [
            {
                "formula_id": "con.retention",
                "name": "Retention",
                "domain": "construction_ops",
                "version": "1.0.0",
                "expression": "certified * rate",
                "inputs": [{"name": "certified"}, {"name": "rate"}],
                "currency": "SAR",
                "precision": 2,
                "authority_source": "PRC-605",
                "certification": "domain_approved",
            }
        ],
        "rules": [
            {
                "rule_id": "con.no_work_before_dd",
                "version": "1.0.0",
                "conditions": [{"field": "work_instruction", "op": "eq", "value": True}],
                "decision": {"outcome": "refuse", "message": "DD approval required"},
                "precedence": 10,
                "refusal_behavior": "refuse",
                "authority_source": "PRC-502",
            }
        ],
        "decision_tables": [],
        "workflows": [
            {
                "workflow_id": "con.ncr",
                "version": "1.0.0",
                "states": ["raised", "under_review", "closed"],
                "initial_state": "raised",
                "terminal_states": ["closed"],
                "transitions": [
                    {"from": "raised", "to": "under_review"},
                    {"from": "under_review", "to": "closed"},
                ],
            }
        ],
        "approvals": [],
        "actions": {"con.issue_ncr": {"risk": "low"}, "con.close_ncr": {"risk": "low"}},
    }
    raw.update(overrides)
    return raw


# -- loader / validator ----------------------------------------------------


def test_valid_pack_loads():
    pack = DomainPackLoader().load(_pack_dict())
    assert pack.manifest.domain_id == "construction_ops"
    assert pack.domain_approved_formulas[0].formula_id == "con.retention"


def test_invalid_pack_is_refused_with_reasons():
    with pytest.raises(PackLoadError) as exc:
        DomainPackLoader().load(_pack_dict(formulas=[{"formula_id": "x", "name": "X"}]))
    assert any("schema" in r for r in exc.value.reasons)


def test_rule_without_conditions_is_refused():
    raw = _pack_dict(
        rules=[{"rule_id": "bad.rule", "version": "1.0.0", "decision": {}}],
    )
    with pytest.raises(PackLoadError) as exc:
        DomainPackLoader().load(raw)
    assert any("matches everything" in r for r in exc.value.reasons)


def test_workflow_with_unknown_state_is_refused():
    raw = _pack_dict(
        workflows=[
            {
                "workflow_id": "bad.wf",
                "version": "1.0.0",
                "states": ["a"],
                "initial_state": "a",
                "terminal_states": [],
                "transitions": [{"from": "a", "to": "zzz"}],
            }
        ]
    )
    with pytest.raises(PackLoadError) as exc:
        DomainPackLoader().load(raw)
    assert any("unknown state" in r for r in exc.value.reasons)


# -- evidence / authority / refusal ----------------------------------------


def test_evidence_missing_item_is_dependency_required():
    engine = EvidenceRequirementEngine({"con.close_ncr": ["photo", "signoff"]})
    out = engine.require("con.close_ncr", {"photo": "p.jpg"})
    assert out.status is ReasoningStatus.DEPENDENCY_REQUIRED
    assert out.missing_inputs == ["evidence:signoff"]


def test_authority_unregistered_is_refused():
    resolver = AuthorityResolver()
    out = resolver.require("con.retention", "PRC-605")
    assert out.status is ReasoningStatus.DEPENDENCY_REQUIRED
    resolver.register("PRC-605", kind="procedure", reference="controlled doc v3")
    ok = resolver.require("con.retention", "PRC-605")
    assert ok.status is ReasoningStatus.SUCCESS
    assert ok.authority_sources[0]["resolved"] is True


def test_refusal_engine_names_reasons_and_records_evidence():
    refusal = RefusalEngine()
    out = refusal.unsupported("teleport", supported=["lift", "dig"])
    assert out.status is ReasoningStatus.UNSUPPORTED
    assert out.evidence[0]["reason"] == "unsupported"
    env = refusal.out_of_envelope("extrapolate", envelope={"region": "eu"})
    assert env.status is ReasoningStatus.VALIDATION_ERROR
    assert "refusing rather than extrapolating" in env.explanation


def test_assumptions_are_declared_not_silent():
    reg = AssumptionRegistry()
    reg.declare("fx_rate", "1 SAR = 1 SAR (local currency)")
    assert reg.has("fx_rate")
    assert reg.all()[0]["chosen_by"] == "engine"


# -- provenance ------------------------------------------------------------


def test_provenance_chain_verifies_and_detects_tamper():
    recorder = ProvenanceRecorder()
    recorder.record("formula.evaluated", {"formula_id": "con.retention"})
    recorder.record("rule.matched", {"rule_id": "con.no_work_before_dd"})
    assert recorder.verify() == []
    # Tamper with the first record: the chain must break.
    recorder._records[0]["payload"]["formula_id"] = "con.tampered"
    broken = recorder.verify()
    assert broken, "tampering must break the chain"


# -- explanation + oracles --------------------------------------------------


def test_explanation_is_built_from_engine_output_only():
    result = ReasoningResult(
        status=ReasoningStatus.SUCCESS,
        formulas_applied=[
            {"name": "Retention", "output": "50.00", "units": {"output": "SAR"}, "authority_source": "PRC-605"}
        ],
        rules_applied=[{"rule_id": "con.r1", "decision": {"message": "hold"}}],
    )
    text = ExplanationComposer().compose(result)
    assert "Retention = 50.00 SAR" in text
    assert "PRC-605" in text
    assert "con.r1: hold" in text


def _oracle_fn(**inputs):
    return Decimal(inputs["certified"]) * Decimal(inputs["rate"])


def test_oracle_runner_passes_known_answers_and_fails_on_mismatch():
    runner = VerificationOracleRunner()
    oracle = {
        "function": "tests.core.test_reasoning_kernel_slice._oracle_fn",
        "cases": [
            {"inputs": {"certified": "100", "rate": "0.05"}, "expected": "5.00"},
        ],
    }
    ok = runner.run("con.retention", oracle)
    assert ok.status is ReasoningStatus.SUCCESS
    bad = dict(oracle, cases=[{"inputs": {"certified": "100", "rate": "0.05"}, "expected": "9.99"}])
    failed = runner.run("con.retention", bad)
    assert failed.status is ReasoningStatus.VALIDATION_ERROR
    assert failed.evidence[0]["kind"] == "oracle_failure"


# -- version manager -------------------------------------------------------


def test_version_mismatch_is_refused_by_name():
    pack = DomainPackLoader().load(_pack_dict())
    manager = DomainPackVersionManager(pack)
    manager.pin("1.0.0")
    assert manager.verify("1.0.0").status is ReasoningStatus.SUCCESS
    out = manager.verify("1.1.0")
    assert out.status is ReasoningStatus.CONFLICT_DETECTED
    assert out.versions == {"pinned": "1.0.0", "running": "1.1.0"}


# -- planner + action plan validator ---------------------------------------


def test_planner_names_what_would_run():
    pack = DomainPackLoader().load(_pack_dict())
    plan = ReasoningPlanner(pack).plan("raise an NCR", {"work_instruction": True})
    assert plan.status is ReasoningStatus.SUCCESS
    rules_item = plan.recommended_actions[0]
    assert any("con.no_work_before_dd" == r["rule_id"] for r in rules_item["items"])


def test_action_plan_refuses_undeclared_action_and_trusted_overrides():
    pack = DomainPackLoader().load(_pack_dict())
    validator = ActionPlanValidator(pack)
    ok = validator.validate([{"action": "con.issue_ncr"}])
    assert ok.status is ReasoningStatus.SUCCESS
    unknown = validator.validate([{"action": "con.teleport"}])
    assert unknown.status is ReasoningStatus.VALIDATION_ERROR
    assert "not a declared pack action" in unknown.explanation
    overridden = validator.validate([{"action": "con.issue_ncr", "approval": "self"}])
    assert overridden.status is ReasoningStatus.VALIDATION_ERROR
    assert "trusted field" in overridden.explanation


# -- conflict detector -----------------------------------------------------


def test_conflict_detector_flags_divergent_definitions():
    detector = ConflictDetector()
    assert detector.register("con.retention", "1.0.0", {"rate": "0.05"}, domain="construction_ops") is None
    conflict = detector.register("con.retention", "1.1.0", {"rate": "0.10"}, domain="construction_ops")
    assert conflict is not None
    assert conflict["versions"] == ["1.0.0", "1.1.0"]
    # conflicts() must accumulate the recorded conflict, not return []
    assert detector.conflicts() == [conflict]
    # a later registration with the SAME content as the registered one is
    # not a conflict (the divergent 1.1.0 was never registered)
    assert detector.register("con.retention", "1.0.0", {"rate": "0.05"}, domain="construction_ops") is None
    assert len(detector.conflicts()) == 1
