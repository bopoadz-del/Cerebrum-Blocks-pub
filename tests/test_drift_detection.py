"""Drift detection in the LearningEngine + CredibilityScorer.

Phase 1 of the auto-retraining pipeline (docs/design/auto-retraining.md):
the engine must detect when a formula's accuracy has degraded since the
last tier change and emit a structured drift event. These tests pin
that behaviour end-to-end against the block API plus the underlying
``CredibilityScorer.detect_drift`` primitive.
"""

from __future__ import annotations

import json
import os

import pytest

from app.blocks.learning_engine import LearningEngineBlock
from app.core.learning_store import FileLearningStore
from app.core.credibility import (
    CredibilityRecord,
    CredibilityScorer,
    CredibilityTier,
)


# ── CredibilityScorer.detect_drift — pure-function checks ───────────────


def test_detect_drift_requires_min_samples():
    """Even with a huge accuracy delta, sample_size below the floor must
    NOT trigger drift — variance dominates at low N."""
    scorer = CredibilityScorer()
    rec = CredibilityRecord(
        item_id="formula:x",
        tier=CredibilityTier.OPERATIONAL,
        accuracy=0.5,
        sample_size=5,                     # below the 20-sample floor
        accuracy_at_promotion=0.95,
    )
    # Big delta — but should still be False because of the sample gate.
    assert scorer.detect_drift(rec, current_accuracy=0.5) is False


def test_detect_drift_fires_above_threshold():
    scorer = CredibilityScorer()
    rec = CredibilityRecord(
        item_id="formula:x",
        tier=CredibilityTier.OPERATIONAL,
        accuracy=0.7,
        sample_size=50,
        accuracy_at_promotion=0.90,
    )
    # 0.20 drop is well above the 0.10 default threshold.
    assert scorer.detect_drift(rec, current_accuracy=0.70) is True


def test_detect_drift_below_threshold_returns_false():
    scorer = CredibilityScorer()
    rec = CredibilityRecord(
        item_id="formula:x",
        tier=CredibilityTier.OPERATIONAL,
        accuracy=0.86,
        sample_size=50,
        accuracy_at_promotion=0.90,
    )
    # Only 0.04 drop — under the 0.10 threshold.
    assert scorer.detect_drift(rec, current_accuracy=0.86) is False


def test_evaluate_promotion_updates_accuracy_at_promotion():
    """When a tier change happens, accuracy_at_promotion must be
    refreshed to the current accuracy — that becomes the new baseline."""
    scorer = CredibilityScorer()
    rec = CredibilityRecord(item_id="formula:x")
    assert rec.accuracy_at_promotion == 0.0

    scorer.evaluate_promotion(rec, accuracy=0.97, sample_size=150)
    assert rec.tier == CredibilityTier.CERTIFIED
    assert rec.accuracy_at_promotion == pytest.approx(0.97)

    # No tier change → no rewrite.
    scorer.evaluate_promotion(rec, accuracy=0.96, sample_size=160)
    assert rec.tier == CredibilityTier.CERTIFIED
    assert rec.accuracy_at_promotion == pytest.approx(0.97)


def test_credibility_record_round_trips_accuracy_at_promotion():
    rec = CredibilityRecord(
        item_id="x",
        tier=CredibilityTier.OPERATIONAL,
        accuracy=0.88,
        sample_size=42,
        accuracy_at_promotion=0.91,
    )
    restored = CredibilityRecord.from_dict(rec.to_dict())
    assert restored.accuracy_at_promotion == pytest.approx(0.91)


# ── LearningEngineBlock — integration with state + drift events ─────────


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """Return a fresh LearningEngineBlock pointing at a tmp state file.

    Keep CELERY_BROKER_URL unset so the retrain enqueue falls back to
    the pending_retrains list — that's the in-CI default and one of the
    things this fixture is here to lock in.
    """
    storage = tmp_path / "learning_state.json"
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    block = LearningEngineBlock(
        config={"storage_backend": FileLearningStore(str(storage))}
    )
    return block


def _seed_promoted_formula(
    engine: LearningEngineBlock,
    formula_id: str,
    *,
    tier: CredibilityTier = CredibilityTier.OPERATIONAL,
    accuracy_at_promotion: float = 0.95,
    sample_size: int = 50,
) -> None:
    """Plant a credibility record that's already been promoted, so that
    drift detection has a non-zero baseline to compare against. We also
    pre-fill the sample list with rows that match
    ``accuracy_at_promotion`` so the engine's rolling accuracy starts
    where the persisted credibility says it does — without that, the
    very first new correction would single-handedly recompute accuracy
    from scratch and demote the formula before drift logic can fire."""
    # Generate samples whose 1 - MAPE matches accuracy_at_promotion.
    # Using err = (1 - accuracy) so each sample contributes uniformly.
    err = max(0.0, min(1.0, 1.0 - float(accuracy_at_promotion)))
    seeded_samples = [
        {"predicted": 100.0, "actual": 100.0 * (1.0 - err), "ts": 0.0}
        for _ in range(sample_size)
    ]
    engine._state.setdefault("formulas", {})[formula_id] = {
        "samples": seeded_samples,
        "tier": "gold",
        "coefficients": {"scale": 1.0, "bias": 0.0},
        "executions": sample_size,
        "created_at": 0.0,
        "credibility": CredibilityRecord(
            item_id=formula_id,
            tier=tier,
            accuracy=accuracy_at_promotion,
            sample_size=sample_size,
            accuracy_at_promotion=accuracy_at_promotion,
        ).to_dict(),
    }
    engine._save_state()


@pytest.mark.asyncio
async def test_new_formula_no_drift_event(engine):
    """A brand-new formula has no baseline; first correction must not
    fire drift."""
    result = await engine._record_correction(
        {"formula_id": "concrete_cost", "predicted": 100.0, "actual": 90.0},
        {},
    )
    assert result["status"] == "success"
    assert result["credibility"]["drift_detected"] is False
    assert "drift_events" not in engine._state or not engine._state["drift_events"]


@pytest.mark.asyncio
async def test_drift_detected_after_accuracy_collapse(engine):
    """Seed a high-baseline OPERATIONAL formula, then submit ~25 bad
    corrections. Drift must fire and the tier must demote."""
    formula_id = "concrete_cost"
    _seed_promoted_formula(
        engine,
        formula_id,
        tier=CredibilityTier.OPERATIONAL,
        accuracy_at_promotion=0.95,
        sample_size=50,
    )

    # Track whether drift fired on ANY step. Once a drift event fires,
    # `accuracy_at_promotion` is rewritten to the new (lower) accuracy
    # — so the per-correction `drift_detected` flag may flip back to
    # False on later steps. The contract under test is "drift was
    # detected at least once across this stream", which the persisted
    # drift_events list captures.
    drift_seen_inline = False
    last_result = None
    for _ in range(25):
        last_result = await engine._record_correction(
            {"formula_id": formula_id, "predicted": 100.0, "actual": 70.0},
            {},
        )
        if last_result["credibility"]["drift_detected"]:
            drift_seen_inline = True

    assert last_result is not None
    assert last_result["status"] == "success"
    assert drift_seen_inline is True

    # Must have demoted out of OPERATIONAL.
    final_tier_name = engine._state["formulas"][formula_id]["credibility"]["tier_name"]
    assert final_tier_name in {"EXPERIMENTAL", "UNVERIFIED", "QUARANTINE"}

    # Drift events persisted.
    drift_events = engine._state.get("drift_events", [])
    assert any(e["formula_id"] == formula_id for e in drift_events)
    event = next(e for e in drift_events if e["formula_id"] == formula_id)
    assert event["from_accuracy"] == pytest.approx(0.95)
    assert event["to_accuracy"] < event["from_accuracy"]


@pytest.mark.asyncio
async def test_pending_retrain_recorded_when_celery_unavailable(engine, monkeypatch):
    """No Celery broker configured → drift on a sub-OPERATIONAL formula
    must enqueue into ``pending_retrains`` instead of raising."""
    formula_id = "concrete_cost"
    _seed_promoted_formula(
        engine,
        formula_id,
        tier=CredibilityTier.OPERATIONAL,
        accuracy_at_promotion=0.95,
        sample_size=50,
    )

    # Force the import path to fail so we exercise the fallback branch
    # (the SyncTask.delay() path otherwise succeeds silently).
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "app.tasks.learning_retrain", None)

    for _ in range(25):
        await engine._record_correction(
            {"formula_id": formula_id, "predicted": 100.0, "actual": 70.0},
            {},
        )

    pending = engine._state.get("pending_retrains", [])
    assert any(p["formula_id"] == formula_id for p in pending)


@pytest.mark.asyncio
async def test_drift_event_persists_to_state_file(engine, tmp_path):
    """The drift_events list must survive a state-file round-trip — that's
    what auditors read."""
    formula_id = "rebar_qty"
    _seed_promoted_formula(
        engine,
        formula_id,
        tier=CredibilityTier.OPERATIONAL,
        accuracy_at_promotion=0.95,
        sample_size=50,
    )

    for _ in range(25):
        await engine._record_correction(
            {"formula_id": formula_id, "predicted": 100.0, "actual": 65.0},
            {},
        )

    storage_path = engine.config["storage_backend"].path
    assert os.path.exists(storage_path)
    with open(storage_path) as f:
        on_disk = json.load(f)
    assert any(
        e["formula_id"] == formula_id for e in on_disk.get("drift_events", [])
    )


@pytest.mark.asyncio
async def test_record_correction_returns_drift_keys(engine):
    """The shape contract: every successful correction surfaces the
    credibility/tier/drift bundle so downstream UIs can react."""
    result = await engine._record_correction(
        {"formula_id": "x", "predicted": 100.0, "actual": 99.0},
        {},
    )
    assert result["status"] == "success"
    cred = result["credibility"]
    assert "tier" in cred
    assert "previous_tier" in cred
    assert "accuracy" in cred
    assert "sample_size" in cred
    assert "drift_detected" in cred
    assert "promoted" in cred
