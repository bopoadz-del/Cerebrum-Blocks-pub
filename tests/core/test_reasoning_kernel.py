"""Reasoning Kernel core — behavior tests.

Each engine is proven both ways: the correct path AND a named refusal.
A check that cannot fail is worse than no check.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.reasoning_kernel import ReasoningResult, ReasoningStatus
from app.reasoning_kernel.approvals import ApprovalMatrixEngine
from app.reasoning_kernel.formulas import DeterministicFormulaExecutor, FormulaRegistry
from app.reasoning_kernel.rules import DecisionTableEngine, RuleEngine
from app.reasoning_kernel.schemas import (
    ApprovalPolicySpec,
    Certification,
    DecisionTableSpec,
    FormulaSpec,
    RuleSpec,
    WorkflowSpec,
)
from app.reasoning_kernel.workflow import WorkflowEngine


# -- formulas -------------------------------------------------------------


def _retention_spec(certification: Certification = Certification.DOMAIN_APPROVED) -> FormulaSpec:
    return FormulaSpec(
        formula_id="finance.retention",
        name="Retention held",
        domain="finance_ops",
        version="1.0.0",
        description="retention = certified * rate",
        expression="certified * rate",
        inputs=[{"name": "certified", "type": "decimal"}, {"name": "rate", "type": "decimal"}],
        currency="SAR",
        precision=2,
        rounding="half_even",
        preconditions=["rate ge 0", "rate le 1"],
        authority_source="PRC-605",
        certification=certification,
    )


def _registry() -> FormulaRegistry:
    reg = FormulaRegistry()
    reg.register(
        _retention_spec(),
        lambda i: i["certified"] * i["rate"],
    )
    return reg


def test_formula_executes_decimal_and_records_provenance():
    out = DeterministicFormulaExecutor(_registry()).execute(
        "finance.retention", {"certified": "1000.00", "rate": "0.05"}, currency="SAR"
    )
    assert out.status is ReasoningStatus.SUCCESS
    applied = out.formulas_applied[0]
    assert applied["raw"] == "50.0000"
    assert applied["output"] == "50.00"
    assert applied["authority_source"] == "PRC-605"
    assert applied["version"] == "1.0.0"
    assert out.output_digest.startswith("sha256:")


def test_formula_missing_input_is_dependency_required():
    out = DeterministicFormulaExecutor(_registry()).execute("finance.retention", {"certified": "100"})
    assert out.status is ReasoningStatus.DEPENDENCY_REQUIRED
    assert "rate" in out.missing_inputs


def test_formula_currency_mismatch_fails_closed():
    out = DeterministicFormulaExecutor(_registry()).execute(
        "finance.retention", {"certified": "100", "rate": "0.05"}, currency="USD"
    )
    assert out.status is ReasoningStatus.VALIDATION_ERROR
    assert "mixed currencies" in out.explanation


def test_formula_precondition_refuses():
    out = DeterministicFormulaExecutor(_registry()).execute(
        "finance.retention", {"certified": "100", "rate": "1.5"}, currency="SAR"
    )
    assert out.status is ReasoningStatus.VALIDATION_ERROR
    assert "precondition failed" in out.explanation


def test_production_mode_refuses_non_domain_approved_formula():
    reg = FormulaRegistry()
    reg.register(_retention_spec(certification=Certification.TECHNICALLY_VERIFIED), lambda i: Decimal("1"))
    out = DeterministicFormulaExecutor(reg, production=True).execute(
        "finance.retention", {"certified": "100", "rate": "0.05"}, currency="SAR"
    )
    assert out.status is ReasoningStatus.PERMISSION_DENIED


def test_formula_bool_input_is_refused():
    out = DeterministicFormulaExecutor(_registry()).execute(
        "finance.retention", {"certified": True, "rate": "0.05"}, currency="SAR"
    )
    assert out.status is ReasoningStatus.VALIDATION_ERROR
    assert "booleans" in out.explanation


# -- rules -----------------------------------------------------------------


def test_rule_matches_and_records():
    engine = RuleEngine(
        [
            RuleSpec(
                rule_id="con.no_work_before_dd",
                version="1.0.0",
                conditions=[{"field": "work_instruction", "op": "eq", "value": True}],
                decision={"outcome": "refuse", "message": "DD approval required (PRC-502)"},
                precedence=10,
                refusal_behavior="refuse",
                authority_source="PRC-502",
            )
        ]
    )
    out = engine.evaluate({"work_instruction": True})
    assert out.status is ReasoningStatus.VALIDATION_ERROR
    assert out.rules_applied[0]["rule_id"] == "con.no_work_before_dd"
    assert "PRC-502" in out.explanation


def test_rule_exception_path_matches_nothing():
    engine = RuleEngine(
        [
            RuleSpec(
                rule_id="con.no_work_before_dd",
                version="1.0.0",
                conditions=[{"field": "work_instruction", "op": "eq", "value": True}],
                exceptions=[{"when": {"dd_approved": True}}],
                decision={"outcome": "refuse", "message": "DD approval required"},
                precedence=10,
                refusal_behavior="refuse",
            )
        ]
    )
    out = engine.evaluate({"work_instruction": True, "dd_approved": True})
    assert out.status is ReasoningStatus.SUCCESS
    assert out.rules_applied == []


def test_conflicting_rules_produce_conflict_detected():
    engine = RuleEngine(
        [
            RuleSpec(
                rule_id="a.rule_one",
                version="1.0.0",
                conditions=[{"field": "x", "op": "gt", "value": 5}],
                decision={"outcome": "A"},
                precedence=5,
                refusal_behavior="warn",
            ),
            RuleSpec(
                rule_id="b.rule_two",
                version="1.0.0",
                conditions=[{"field": "x", "op": "gt", "value": 5}],
                decision={"outcome": "B"},
                precedence=5,
                refusal_behavior="warn",
            ),
        ]
    )
    out = engine.evaluate({"x": 7})
    assert out.status is ReasoningStatus.CONFLICT_DETECTED
    assert {"a.rule_one", "b.rule_two"} <= {r["rule_id"] for r in out.rules_applied}


def test_decision_table_exact_match_and_default():
    table = DecisionTableSpec(
        table_id="con.risk_band",
        version="1.0.0",
        inputs=["score"],
        rows=[
            {"when": {"score": {"op": "ge", "value": 16}}, "then": {"band": "RED"}},
            {"when": {"score": {"op": "ge", "value": 9}}, "then": {"band": "AMBER"}},
            {"when": {"score": {"op": "ge", "value": 0}}, "then": {"band": "GREEN"}},
        ],
        default_outcome={"band": "UNSCORED"},
    )
    engine = DecisionTableEngine(table)
    assert engine.evaluate({"score": 20}).recommended_actions[0]["outcome"]["band"] == "RED"
    assert engine.evaluate({"score": -3}).recommended_actions[0]["outcome"]["band"] == "UNSCORED"


# -- workflow --------------------------------------------------------------


def _ncr_workflow() -> WorkflowEngine:
    return WorkflowEngine(
        WorkflowSpec(
            workflow_id="con.ncr",
            version="1.0.0",
            states=["raised", "under_review", "closed"],
            initial_state="raised",
            terminal_states=["closed"],
            transitions=[
                {
                    "from": "raised",
                    "to": "under_review",
                    "permitted_actors": ["qa_engineer"],
                    "evidence_required": ["photo"],
                },
                {"from": "under_review", "to": "closed", "permitted_actors": ["qa_manager"]},
            ],
        )
    )


def test_workflow_valid_and_invalid_transitions():
    engine = _ncr_workflow()
    engine.create("ncr-1")
    refused = engine.transition("ncr-1", "closed", actor="qa_engineer", evidence={"photo": "x"})
    assert refused.status is ReasoningStatus.UNSUPPORTED
    ok = engine.transition("ncr-1", "under_review", actor="qa_engineer", evidence={"photo": "x"})
    assert ok.status is ReasoningStatus.SUCCESS
    assert engine.state("ncr-1")["state"] == "under_review"


def test_workflow_role_and_evidence_refusals_are_named():
    engine = _ncr_workflow()
    engine.create("ncr-2")
    bad_role = engine.transition("ncr-2", "under_review", actor="intern", evidence={"photo": "x"})
    assert bad_role.status is ReasoningStatus.PERMISSION_DENIED
    missing_evidence = engine.transition("ncr-2", "under_review", actor="qa_engineer")
    assert missing_evidence.status is ReasoningStatus.DEPENDENCY_REQUIRED
    assert missing_evidence.missing_inputs == ["evidence:photo"]


def test_workflow_approval_gate_requires_token():
    engine = WorkflowEngine(
        WorkflowSpec(
            workflow_id="con.payment",
            version="1.0.0",
            states=["draft", "certified"],
            initial_state="draft",
            terminal_states=["certified"],
            transitions=[{"from": "draft", "to": "certified", "approval_required": True}],
        )
    )
    engine.create("pay-1")
    refused = engine.transition("pay-1", "certified", actor="qs")
    assert refused.status is ReasoningStatus.APPROVAL_REQUIRED
    engine.register_approval("pay-1", "certified", "appr_token_1")
    ok = engine.transition("pay-1", "certified", actor="qs", approval_token="appr_token_1")
    assert ok.status is ReasoningStatus.SUCCESS
    replay = engine.transition("pay-1", "certified", actor="qs", approval_token="appr_token_1")
    assert replay.status is ReasoningStatus.UNSUPPORTED  # not declared from certified


# -- approvals -------------------------------------------------------------


def _approval_engine() -> ApprovalMatrixEngine:
    return ApprovalMatrixEngine(
        [
            ApprovalPolicySpec(
                action="finance.budget_lock",
                version="1.0.0",
                risk_tier="high",
                requester_roles=["fp_and_a_manager"],
                approver_roles=["controller", "cfo"],
                minimum_approvals=1,
                self_approval="prohibited",
                payload_binding="required",
                expiry_seconds=300,
                replay_prevention="required",
                segregation_of_duties=[["requester", "controller"]],
            )
        ]
    )


def test_approval_flow_grants_with_bound_token():
    engine = _approval_engine()
    payload = {"budget_id": "B-1", "amount": "500000"}
    token = engine.issue(
        "finance.budget_lock",
        approver={"id": "cfo-1", "role": "cfo", "requester_id": "fp-1"},
        payload=payload,
    )
    out = engine.check(
        "finance.budget_lock",
        requester={"id": "fp-1", "role": "fp_and_a_manager"},
        payload=payload,
        value=500000,
        approvals=[{"token": token, "requester_id": "fp-1"}],
    )
    assert out.status is ReasoningStatus.SUCCESS
    assert out.approval["granted"] is True


def test_approval_missing_is_approval_required():
    engine = _approval_engine()
    out = engine.check(
        "finance.budget_lock",
        requester={"id": "fp-1", "role": "fp_and_a_manager"},
        payload={"budget_id": "B-1"},
        value=500000,
        approvals=[],
    )
    assert out.status is ReasoningStatus.APPROVAL_REQUIRED
    assert out.approval["minimum_approvals"] == 1


def test_self_approval_is_refused_at_issue():
    engine = _approval_engine()
    with pytest.raises(Exception, match="self-approval prohibited"):
        engine.issue(
            "finance.budget_lock",
            approver={"id": "fp-1", "role": "controller", "requester_id": "fp-1"},
            payload={"budget_id": "B-1"},
        )


def test_wrong_role_cannot_approve():
    engine = _approval_engine()
    with pytest.raises(Exception, match="cannot approve"):
        engine.issue(
            "finance.budget_lock",
            approver={"id": "j-1", "role": "intern", "requester_id": "fp-1"},
            payload={"budget_id": "B-1"},
        )


def test_payload_binding_rejects_tampered_payload():
    engine = _approval_engine()
    payload = {"budget_id": "B-1", "amount": "500000"}
    token = engine.issue(
        "finance.budget_lock",
        approver={"id": "cfo-1", "role": "cfo", "requester_id": "fp-1"},
        payload=payload,
    )
    out = engine.check(
        "finance.budget_lock",
        requester={"id": "fp-1", "role": "fp_and_a_manager"},
        payload={"budget_id": "B-1", "amount": "999999"},
        value=500000,
        approvals=[{"token": token, "requester_id": "fp-1"}],
    )
    assert out.status is ReasoningStatus.APPROVAL_REQUIRED


def test_approval_replay_is_refused():
    engine = _approval_engine()
    payload = {"budget_id": "B-1"}
    token = engine.issue(
        "finance.budget_lock",
        approver={"id": "cfo-1", "role": "cfo", "requester_id": "fp-1"},
        payload=payload,
    )
    approval = {"token": token, "requester_id": "fp-1"}
    first = engine.check(
        "finance.budget_lock",
        requester={"id": "fp-1", "role": "fp_and_a_manager"},
        payload=payload,
        value=500000,
        approvals=[approval],
    )
    assert first.status is ReasoningStatus.SUCCESS
    second = engine.check(
        "finance.budget_lock",
        requester={"id": "fp-1", "role": "fp_and_a_manager"},
        payload=payload,
        value=500000,
        approvals=[approval],
    )
    assert second.status is ReasoningStatus.APPROVAL_REQUIRED


def test_high_risk_policy_without_thresholds_still_requires_approval():
    """The authorization bug this test pins: an empty threshold map must
    never degrade a high-risk action to no-approval-required."""
    engine = _approval_engine()
    out = engine.check(
        "finance.budget_lock",
        requester={"id": "fp-1", "role": "fp_and_a_manager"},
        payload={"budget_id": "B-1"},
        value=1,  # tiny value, no thresholds declared
        approvals=[],
    )
    assert out.status is ReasoningStatus.APPROVAL_REQUIRED
    assert out.approval["required"] is True


def test_emergency_override_requires_role_and_justification():
    engine = _approval_engine()
    refused = engine.emergency_override(
        "finance.budget_lock",
        admin={"id": "fp-1", "role": "fp_and_a_manager"},
        payload={"budget_id": "B-1"},
        justification="incident",
    )
    assert refused.status is ReasoningStatus.PERMISSION_DENIED
