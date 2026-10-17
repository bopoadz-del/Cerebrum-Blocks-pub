"""Tests for the 5-Tier Credibility System (`app/core/credibility.py`)."""

from __future__ import annotations

import time

import pytest

from app.core.credibility import (
    CredibilityRecord,
    CredibilityScorer,
    CredibilityTier,
)


# ── score() — tier thresholds ───────────────────────────────────────────


@pytest.mark.parametrize(
    "accuracy,sample_size,expected",
    [
        # Certified: ≥0.95 accuracy AND ≥100 samples
        (1.00, 200, CredibilityTier.CERTIFIED),
        (0.95, 100, CredibilityTier.CERTIFIED),
        # Operational: ≥0.85 accuracy AND ≥30 samples
        (0.90, 50, CredibilityTier.OPERATIONAL),
        (0.85, 30, CredibilityTier.OPERATIONAL),
        # Experimental: ≥0.70 accuracy AND ≥10 samples
        (0.75, 15, CredibilityTier.EXPERIMENTAL),
        (0.70, 10, CredibilityTier.EXPERIMENTAL),
        # UNVERIFIED — sample size below the experimental floor.
        (0.99, 5, CredibilityTier.UNVERIFIED),
        (0.50, 9, CredibilityTier.UNVERIFIED),
        # QUARANTINE — accuracy below 0.50 with enough samples to judge.
        (0.30, 100, CredibilityTier.QUARANTINE),
        (0.10, 50, CredibilityTier.QUARANTINE),
    ],
)
def test_score_thresholds(accuracy, sample_size, expected):
    scorer = CredibilityScorer()
    assert scorer.score(accuracy, sample_size) == expected


def test_score_clamps_inputs_into_valid_range():
    scorer = CredibilityScorer()
    # Negative or >1 accuracy gets clamped, not raised.
    assert scorer.score(-0.5, 100) == CredibilityTier.QUARANTINE
    assert scorer.score(1.7, 200) == CredibilityTier.CERTIFIED
    assert scorer.score(0.5, -10) == CredibilityTier.UNVERIFIED


def test_low_sample_size_never_quarantines():
    """Quarantine requires enough samples to be confident — guard the floor."""
    scorer = CredibilityScorer()
    assert scorer.score(0.0, 5) == CredibilityTier.UNVERIFIED


# ── should_surface() — audience visibility rules ────────────────────────


@pytest.mark.parametrize(
    "tier,audience,expected",
    [
        (CredibilityTier.CERTIFIED, "user", True),
        (CredibilityTier.CERTIFIED, "staff", True),
        (CredibilityTier.OPERATIONAL, "user", True),
        (CredibilityTier.OPERATIONAL, "staff", True),
        (CredibilityTier.EXPERIMENTAL, "user", False),
        (CredibilityTier.EXPERIMENTAL, "staff", True),
        (CredibilityTier.UNVERIFIED, "user", False),
        (CredibilityTier.UNVERIFIED, "staff", True),
        (CredibilityTier.QUARANTINE, "user", False),
        (CredibilityTier.QUARANTINE, "staff", False),
    ],
)
def test_should_surface(tier, audience, expected):
    scorer = CredibilityScorer()
    assert scorer.should_surface(tier, audience) is expected


def test_should_surface_rejects_unknown_audience():
    scorer = CredibilityScorer()
    with pytest.raises(ValueError):
        scorer.should_surface(CredibilityTier.CERTIFIED, "anonymous")  # type: ignore[arg-type]


# ── evaluate_promotion() — history bookkeeping ──────────────────────────


def test_evaluate_promotion_appends_history_on_change():
    scorer = CredibilityScorer()
    rec = CredibilityRecord(item_id="formula:concrete_cost")
    assert rec.tier == CredibilityTier.UNVERIFIED
    assert rec.promotion_history == []

    # Big jump straight to CERTIFIED — should record the transition.
    updated = scorer.evaluate_promotion(rec, accuracy=0.97, sample_size=150)
    assert updated.tier == CredibilityTier.CERTIFIED
    assert len(updated.promotion_history) == 1
    entry = updated.promotion_history[0]
    assert entry["from_name"] == "UNVERIFIED"
    assert entry["to_name"] == "CERTIFIED"
    assert entry["from"] == int(CredibilityTier.UNVERIFIED)
    assert entry["to"] == int(CredibilityTier.CERTIFIED)
    assert "at" in entry and isinstance(entry["at"], float)
    assert "reason" in entry and entry["reason"]
    assert entry["accuracy"] == pytest.approx(0.97)
    assert entry["sample_size"] == 150


def test_evaluate_promotion_no_change_no_history_entry():
    scorer = CredibilityScorer()
    rec = CredibilityRecord(item_id="formula:rebar_qty")

    # First call: UNVERIFIED → UNVERIFIED (still under sample floor).
    scorer.evaluate_promotion(rec, accuracy=0.99, sample_size=3)
    assert rec.tier == CredibilityTier.UNVERIFIED
    assert rec.promotion_history == []

    # Second call: still UNVERIFIED — no new entry should be appended.
    scorer.evaluate_promotion(rec, accuracy=0.95, sample_size=8)
    assert rec.tier == CredibilityTier.UNVERIFIED
    assert rec.promotion_history == []


def test_evaluate_promotion_records_demotion():
    """A demotion from CERTIFIED to QUARANTINE must also be logged."""
    scorer = CredibilityScorer()
    rec = CredibilityRecord(item_id="formula:risky")
    scorer.evaluate_promotion(rec, accuracy=0.97, sample_size=200)
    assert rec.tier == CredibilityTier.CERTIFIED

    # Now its accuracy collapses with plenty of samples.
    scorer.evaluate_promotion(rec, accuracy=0.20, sample_size=300, reason="failed audit")
    assert rec.tier == CredibilityTier.QUARANTINE
    assert len(rec.promotion_history) == 2
    last = rec.promotion_history[-1]
    assert last["from_name"] == "CERTIFIED"
    assert last["to_name"] == "QUARANTINE"
    assert last["reason"] == "failed audit"


def test_evaluate_promotion_updates_last_updated():
    scorer = CredibilityScorer()
    rec = CredibilityRecord(item_id="x", last_updated=0.0)
    before = time.time()
    scorer.evaluate_promotion(rec, accuracy=0.9, sample_size=40)
    assert rec.last_updated >= before


def test_record_round_trips_through_dict():
    rec = CredibilityRecord(
        item_id="r1",
        tier=CredibilityTier.OPERATIONAL,
        accuracy=0.88,
        sample_size=42,
    )
    rec.promotion_history.append({
        "from": int(CredibilityTier.UNVERIFIED),
        "to": int(CredibilityTier.OPERATIONAL),
        "at": time.time(),
        "reason": "manual seed",
    })
    blob = rec.to_dict()
    restored = CredibilityRecord.from_dict(blob)
    assert restored.item_id == "r1"
    assert restored.tier == CredibilityTier.OPERATIONAL
    assert restored.accuracy == 0.88
    assert restored.sample_size == 42
    assert restored.promotion_history == rec.promotion_history
