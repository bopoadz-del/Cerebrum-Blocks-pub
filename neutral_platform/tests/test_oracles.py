"""Known-answer oracles for the neutral pack's formulas (mission Phase 6).

Truth comes from the pack's own worked examples, run through the kernel's
DeterministicFormulaExecutor — not reimplemented arithmetic in the test.
"""

from __future__ import annotations

import pytest

from app.reasoning_kernel import ReasoningStatus
from neutral_app.platform import NeutralPlatform


@pytest.fixture(scope="module")
def platform():
    return NeutralPlatform()


def test_risk_score_known_answers(platform):
    cases = [
        ({"likelihood": 1, "consequence": 1}, "1"),
        ({"likelihood": 5, "consequence": 5}, "25"),
        ({"likelihood": 2, "consequence": 3}, "6"),
        ({"likelihood": 4, "consequence": 4}, "16"),
    ]
    for inputs, expected in cases:
        result = platform.formulas.execute(
            "equipment_maintenance.risk_score", inputs, domain="equipment_maintenance"
        )
        assert result.status is ReasoningStatus.SUCCESS
        assert result.formulas_applied[0]["output"] == expected
        assert result.output_digest, "every result must carry digests"


def test_risk_score_boundary_refusals(platform):
    for bad in ({"likelihood": 0, "consequence": 3}, {"likelihood": 6, "consequence": 3}):
        result = platform.formulas.execute(
            "equipment_maintenance.risk_score", bad, domain="equipment_maintenance"
        )
        assert result.status is ReasoningStatus.VALIDATION_ERROR
        assert "precondition" in result.explanation


def test_risk_score_refuses_boolean_input(platform):
    result = platform.formulas.execute(
        "equipment_maintenance.risk_score",
        {"likelihood": True, "consequence": 3},
        domain="equipment_maintenance",
    )
    assert result.status is ReasoningStatus.VALIDATION_ERROR
    assert "boolean" in result.explanation


def test_service_overdue_known_answers(platform):
    cases = [
        ({"hours_since_service": 520, "service_interval_hours": 500}, "True"),
        ({"hours_since_service": 500, "service_interval_hours": 500}, "True"),
        ({"hours_since_service": 499, "service_interval_hours": 500}, "False"),
    ]
    for inputs, expected in cases:
        result = platform.formulas.execute(
            "equipment_maintenance.service_overdue", inputs, domain="equipment_maintenance"
        )
        assert result.status is ReasoningStatus.SUCCESS
        assert result.formulas_applied[0]["output"] == expected


def test_production_mode_refuses_non_domain_approved(platform, monkeypatch):
    from app.reasoning_kernel.schemas import Certification

    spec = platform._formula_spec("equipment_maintenance.risk_score")
    monkeypatch.setattr(
        spec, "certification", Certification.CANDIDATE, raising=False
    )
    result = platform.formulas.execute(
        "equipment_maintenance.risk_score",
        {"likelihood": 3, "consequence": 3},
        domain="equipment_maintenance",
    )
    assert result.status is ReasoningStatus.PERMISSION_DENIED
    assert "domain_approved" in result.explanation
