"""Tests for the neutral structured outcomes sub-kit."""

import pytest

from block_store.kits.universal_kernel.wave3.structured_outcomes import (
    Outcome,
    OutcomeBuilder,
    OutcomeStatus,
    OutcomeValidationError,
    combine,
)


def test_outcome_success():
    outcome = Outcome(OutcomeStatus.success, data={"id": 1})
    assert outcome.to_dict()["status"] == "success"


def test_outcome_validation_error():
    with pytest.raises(OutcomeValidationError):
        Outcome("weird", data={})  # type: ignore[arg-type]


def test_outcome_builder():
    result = (
        OutcomeBuilder()
        .add("id", 1)
        .add_evidence({"source": "doc-1"})
        .warn("low confidence")
        .build()
    )
    assert result["data"]["id"] == 1
    assert result["evidence"]
    assert "low confidence" in result["warnings"]


def test_combine_worst_case():
    outcomes = [
        Outcome(OutcomeStatus.success, data={"a": 1}),
        Outcome(OutcomeStatus.failure, data={"b": 2}),
    ]
    combined = combine(outcomes)
    assert combined["status"] == "failure"
    assert combined["data"] == {"a": 1, "b": 2}


def test_combine_empty_raises():
    with pytest.raises(OutcomeValidationError):
        combine([])


def test_combine_honesty_warnings():
    outcomes = [
        Outcome(OutcomeStatus.success, honesty="fallback"),
        Outcome(OutcomeStatus.success, honesty="direct"),
    ]
    combined = combine(outcomes)
    assert "outcome used honesty=fallback" in combined["warnings"]
