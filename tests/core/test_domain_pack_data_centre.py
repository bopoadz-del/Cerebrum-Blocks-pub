"""The data-centre governance pack, exercised through the REAL kernel
engines in the store — DomainPackLoader validation, RuleEngine refusals,
DecisionTableEngine tables, DeterministicFormulaExecutor oracles, and
ApprovalMatrixEngine gates. This is the standalone reasoning layer for
data-centre construction.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.reasoning_kernel import ReasoningStatus
from app.reasoning_kernel.approvals import ApprovalMatrixEngine
from app.reasoning_kernel.formulas import (
    DeterministicFormulaExecutor,
    FormulaRegistry,
)
from app.reasoning_kernel.loader import DomainPackLoader
from app.reasoning_kernel.rules import DecisionTableEngine, RuleEngine

PACK_PATH = "domain_packs/data_centre_construction/pack.json"


def _pue(inputs):
    return inputs["total_facility_power"] / inputs["it_load"]


def _load_pct(inputs):
    return (inputs["achieved_load"] / inputs["design_load"]) * Decimal(100)


@pytest.fixture(scope="module")
def pack():
    return DomainPackLoader().load_path(PACK_PATH)


@pytest.fixture(scope="module")
def engines(pack):
    registry = FormulaRegistry()
    registry.register(pack.formulas[0], _pue)  # data_centre_construction.pue
    registry.register(pack.formulas[1], _load_pct)  # test_load_percentage
    return {
        "formulas": DeterministicFormulaExecutor(registry, production=False),
        "rules": RuleEngine(pack.rules),
        "approvals": ApprovalMatrixEngine(pack.approvals),
    }


def test_pack_loads_and_declares_candidate(pack):
    assert pack.manifest.domain_id == "data_centre_construction"
    assert pack.manifest.certification.value == "candidate"
    # The sheet's blank tables must not have been fabricated.
    assert "lead_times" in pack.tests["blank_tables_not_fabricated"]


def test_pue_oracle(engines):
    result = engines["formulas"].execute(
        "data_centre_construction.pue",
        {"total_facility_power": 600, "it_load": 400},
        domain="data_centre_construction",
    )
    assert result.status is ReasoningStatus.SUCCESS
    assert result.formulas_applied[0]["output"] == "1.500"  # precision 3, per the pack
    refused = engines["formulas"].execute(
        "data_centre_construction.pue",
        {"total_facility_power": 600, "it_load": 0},
        domain="data_centre_construction",
    )
    assert refused.status is ReasoningStatus.VALIDATION_ERROR


def test_load_percentage_oracle(engines):
    result = engines["formulas"].execute(
        "data_centre_construction.test_load_percentage",
        {"achieved_load": 300, "design_load": 400},
        domain="data_centre_construction",
    )
    assert result.status is ReasoningStatus.SUCCESS
    assert result.formulas_applied[0]["output"] == "75.0"


@pytest.mark.parametrize(
    "question_class,reason",
    [
        ("are_we_n_plus_1", "requires_live_resilience_state"),
        ("take_string_down", "requires_approved_mop_and_authority"),
        ("will_it_ride_through", "requires_ist_at_load"),
        ("facility_ready_for_it_load", "requires_l5_and_client_acceptance"),
        ("skip_test", "requires_commissioning_authority"),
        ("capacity_for_racks", "requires_measured_capacity"),
    ],
)
def test_refusal_rules_by_name(engines, question_class, reason):
    result = engines["rules"].evaluate(
        {"question_class": question_class},
        domain="data_centre_construction",
    )
    assert result.status is ReasoningStatus.VALIDATION_ERROR
    assert result.prohibited_actions
    assert result.prohibited_actions[0]["decision"]["reason"] == reason


@pytest.mark.parametrize(
    "assertion_kind",
    ["tested_claim", "resilience_claim", "capacity_claim", "readiness_declaration"],
)
def test_absolute_rules_refuse(engines, assertion_kind):
    result = engines["rules"].evaluate(
        {"assertion_kind": assertion_kind},
        domain="data_centre_construction",
    )
    assert result.status is ReasoningStatus.VALIDATION_ERROR
    assert result.prohibited_actions


@pytest.mark.parametrize(
    "inference_kind",
    [
        "system_test_to_facility_performance",
        "partial_load_to_full_load",
        "design_basis_to_current_resilience",
    ],
)
def test_derivation_limits_refuse(engines, inference_kind):
    result = engines["rules"].evaluate(
        {"inference_kind": inference_kind},
        domain="data_centre_construction",
    )
    assert result.status is ReasoningStatus.VALIDATION_ERROR


def test_mandatory_qualifier_gate(engines):
    result = engines["rules"].evaluate(
        {"term": "tested", "level": None},
        domain="data_centre_construction",
    )
    assert result.status is ReasoningStatus.VALIDATION_ERROR
    clean = engines["rules"].evaluate(
        {
            "term": "tested",
            "level": "L3",
            "load_percentage": 75,
            "failure_scenario": "chiller trip",
        },
        domain="data_centre_construction",
    )
    assert clean.status is ReasoningStatus.SUCCESS


def test_staleness_invalidation_fires(engines):
    result = engines["rules"].evaluate(
        {"event": "bypass"},
        domain="data_centre_construction",
    )
    assert any(
        r["decision"].get("action") == "invalidate"
        and r["decision"].get("fact") == "current_resilience_state"
        for r in result.rules_applied
    )


def test_decision_tables(pack):
    quals = DecisionTableEngine(pack.decision_tables[0])
    outcome = quals.evaluate({"term": "tested"}, domain="data_centre_construction")
    assert outcome.recommended_actions[0]["outcome"]["required_qualifiers"] == [
        "level",
        "load_percentage",
        "failure_scenario",
    ]

    evidence = DecisionTableEngine(pack.decision_tables[1])
    outcome = evidence.evaluate(
        {"figure_class": "capacity_available"}, domain="data_centre_construction"
    )
    assert (
        outcome.recommended_actions[0]["outcome"]["unacceptable"]
        == "design capacity stated as available"
    )

    traps = DecisionTableEngine(pack.decision_tables[2])
    outcome = traps.evaluate({"term": "redundancy"}, domain="data_centre_construction")
    assert (
        "N+1 counted as a component instead of a claim"
        in outcome.recommended_actions[0]["outcome"]["confusion_risk"]
    )

    precedence = DecisionTableEngine(pack.decision_tables[3])
    outcome = precedence.evaluate({"rank": 1}, domain="data_centre_construction")
    assert outcome.recommended_actions[0]["outcome"]["source"] == "statutory_safety"


def test_approval_matrix(engines):
    approvals = engines["approvals"]
    refused = approvals.check(
        "skip_test",
        {"role": "project_team", "id": "u1"},
        {"test_id": "t-1"},
        domain="data_centre_construction",
    )
    assert refused.status is ReasoningStatus.APPROVAL_REQUIRED

    token = approvals.issue(
        "skip_test",
        approver={
            "id": "cxa1",
            "role": "commissioning_authority",
            "requester_id": "u1",
        },
        payload={"test_id": "t-1"},
    )
    granted = approvals.check(
        "skip_test",
        {"role": "project_team", "id": "u1"},
        {"test_id": "t-1"},
        approvals=[{"token": token, "requester_id": "u1"}],
        domain="data_centre_construction",
    )
    assert granted.status is ReasoningStatus.SUCCESS

    token1 = approvals.issue(
        "take_string_down",
        approver={
            "id": "cem1",
            "role": "critical_environment_manager",
            "requester_id": "u1",
        },
        payload={"string_id": "s-1"},
    )
    partial = approvals.check(
        "take_string_down",
        {"role": "project_team", "id": "u1"},
        {"string_id": "s-1"},
        approvals=[{"token": token1, "requester_id": "u1"}],
        domain="data_centre_construction",
    )
    assert partial.status is ReasoningStatus.APPROVAL_REQUIRED
    assert partial.approval["valid_approvals"] == 1
