"""learning_engine: the ADVERTISED entry point, which nothing reached.

Across tests/blocks/test_learning_engine_durability.py,
tests/core/test_learning_engine_config.py and tests/test_drift_detection.py,
every test reaches into ``_save_state`` / ``_update_credibility`` / ``_store``
directly. Not one calls ``process()`` or ``execute()``, so the operation
dispatcher -- and every number it returns to a caller -- had no coverage.

These tests drive ``await LearningEngineBlock(...).process(payload)`` and
assert on the coefficient it fitted, the tier it moved a formula to, the
credibility record it recomputed, the state a second block instance reads back
off an injected file store, and the exact text of each refusal.

The stores are injected (MemoryLearningStore / FileLearningStore) because the
block must never choose a path -- same contract the durability suite locks.
"""
from __future__ import annotations

import json

import pytest

from app.blocks.learning_engine import LearningEngineBlock
from app.core.learning_store import FileLearningStore, MemoryLearningStore


def _block(store=None, **config):
    return LearningEngineBlock(
        config={"storage_backend": store or MemoryLearningStore(), **config}
    )


async def _record(block, formula_id, predicted, actual):
    return await block.process({
        "operation": "record_correction",
        "correction_data": {
            "formula_id": formula_id,
            "predicted": predicted,
            "actual": actual,
        },
    })


async def test_process_fits_the_coefficient_that_maps_predicted_onto_actual():
    """Five corrections where the estimate is consistently 10% low must come
    back as scale 1.10 -- the number the caller is expected to apply, not a
    status word."""
    block = _block()
    result = None
    for predicted in (100.0, 250.0, 400.0, 1000.0, 2500.0):
        result = await _record(block, "concrete_cost", predicted, predicted * 1.10)

    assert result["status"] == "success"
    assert result["formula_id"] == "concrete_cost"
    assert result["sample_count"] == 5
    assert result["auto_tuned"] is True
    assert result["updated_coefficients"]["scale"] == pytest.approx(1.10, abs=1e-4)
    assert result["updated_coefficients"]["bias"] == pytest.approx(0.0, abs=1e-3)


async def test_process_does_not_tune_before_it_has_enough_samples():
    """Below min_samples_for_training the block must leave the coefficients
    at identity rather than fit a line through two points."""
    block = _block(min_samples_for_training=5)

    first = await _record(block, "steel_tonnage", 100.0, 110.0)
    second = await _record(block, "steel_tonnage", 200.0, 220.0)

    assert first["auto_tuned"] is False
    assert second["auto_tuned"] is False
    assert second["updated_coefficients"] == {"bias": 0.0, "scale": 1.0}
    assert second["sample_count"] == 2


async def test_process_promotes_the_formula_on_the_execution_that_crosses_the_threshold():
    """bronze -> silver happens at the 10th execution, and the promotion flag
    is raised on exactly that call, not before and not again after."""
    block = _block()
    flags = []
    tiers = []
    for i in range(11):
        r = await _record(block, "rebar_rate", 100.0 + i, 110.0 + i)
        flags.append(r["promotion_flag"])
        tiers.append(r["tier_level"])

    assert tiers[:9] == ["bronze"] * 9
    assert tiers[9] == "silver"
    assert tiers[10] == "silver"
    assert flags.index(True) == 9
    assert flags.count(True) == 1


async def test_process_recomputes_the_credibility_record_it_returns():
    """Ten exact corrections give accuracy 1.0 at sample size 10: enough for
    EXPERIMENTAL, short of the 30 samples OPERATIONAL requires."""
    block = _block()
    result = None
    for i in range(10):
        result = await _record(block, "formwork_area", 500.0 + i, 500.0 + i)

    cred = result["credibility"]
    assert cred["accuracy"] == pytest.approx(1.0)
    assert cred["sample_size"] == 10
    assert cred["previous_tier_name"] == "UNVERIFIED"
    assert cred["tier_name"] == "EXPERIMENTAL"
    assert cred["tier"] == "CredibilityTier.EXPERIMENTAL"
    assert cred["promoted"] is True
    assert cred["drift_detected"] is False


async def test_process_quarantines_a_formula_that_is_consistently_wrong():
    """Accuracy below 0.50 with enough samples must land in QUARANTINE, not
    sit at UNVERIFIED looking merely new."""
    block = _block()
    result = None
    for i in range(12):
        # Predicts double the actual: 100% error, accuracy clamped to 0.
        result = await _record(block, "wild_guess", 200.0 + i, 100.0)

    cred = result["credibility"]
    assert cred["sample_size"] == 12
    assert cred["accuracy"] < 0.5
    assert cred["tier_name"] == "QUARANTINE"


async def test_process_status_reports_the_formulas_it_actually_holds():
    block = _block()
    for i in range(3):
        await _record(block, "concrete_cost", 100.0 + i, 110.0 + i)
    await _record(block, "steel_tonnage", 50.0, 55.0)

    status = await block.process({"operation": "status"})

    assert status["status"] == "success"
    assert status["total_formulas"] == 2
    assert status["tier_distribution"] == {"bronze": 2}
    assert status["formula_summary"]["concrete_cost"]["samples"] == 3
    assert status["formula_summary"]["concrete_cost"]["executions"] == 3
    assert status["formula_summary"]["steel_tonnage"]["samples"] == 1
    assert (
        status["formula_summary"]["concrete_cost"]["credibility"]["tier_name"]
        == "UNVERIFIED"
    )


async def test_process_tune_refits_from_the_history_it_stored():
    block = _block(min_samples_for_training=99)  # keep auto-tune out of it
    for predicted in (100.0, 200.0, 300.0, 400.0):
        await _record(block, "plaster_rate", predicted, predicted * 0.8)

    tuned = await block.process({"operation": "tune", "formula_id": "plaster_rate"})

    assert tuned["status"] == "success"
    assert tuned["formulas_tuned"] == 1
    fit = tuned["tune_results"]["plaster_rate"]
    assert fit["coefficients"]["scale"] == pytest.approx(0.8, abs=1e-4)
    assert fit["mae"] == pytest.approx(0.0, abs=1e-4)
    assert tuned["updated_coefficients"]["plaster_rate"]["scale"] == pytest.approx(
        0.8, abs=1e-4
    )


async def test_process_tune_skips_a_formula_with_too_little_history():
    block = _block()
    await _record(block, "thin", 100.0, 110.0)

    tuned = await block.process({"operation": "tune", "formula_id": "thin"})

    assert tuned["tune_results"]["thin"] == {
        "skipped": True,
        "reason": "insufficient samples",
    }


async def test_process_reset_removes_the_formula_from_stored_state():
    block = _block()
    await _record(block, "concrete_cost", 100.0, 110.0)
    await _record(block, "steel_tonnage", 50.0, 55.0)

    reset = await block.process({"operation": "reset", "formula_id": "concrete_cost"})
    after = await block.process({"operation": "status"})

    assert reset["status"] == "success"
    assert reset["formula_id"] == "concrete_cost"
    assert after["total_formulas"] == 1
    assert "concrete_cost" not in after["formula_summary"]
    assert "steel_tonnage" in after["formula_summary"]


async def test_process_writes_through_to_the_injected_store_so_a_new_block_sees_it(tmp_path):
    """Durability measured through the entry point: what process() recorded
    is on disk, and a second block constructed over the same file reads the
    same samples back."""
    target = tmp_path / "data" / "learning_engine.json"

    first = _block(FileLearningStore(str(target)))
    for predicted in (100.0, 250.0, 400.0, 1000.0, 2500.0):
        await _record(first, "concrete_cost", predicted, predicted * 1.10)

    assert target.is_file()
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert len(on_disk["formulas"]["concrete_cost"]["samples"]) == 5

    second = _block(FileLearningStore(str(target)))
    status = await second.process({"operation": "status"})

    assert status["total_formulas"] == 1
    assert status["formula_summary"]["concrete_cost"]["samples"] == 5
    assert status["formula_summary"]["concrete_cost"]["executions"] == 5

    # A correction recorded by the second block continues the first's history.
    sixth = await _record(second, "concrete_cost", 5000.0, 5500.0)
    assert sixth["sample_count"] == 6
    assert sixth["updated_coefficients"]["scale"] == pytest.approx(1.10, abs=1e-4)


async def test_process_refuses_an_unknown_operation():
    """block.json acceptance criterion 'unknown_action': errors, not
    silently treated as a status query."""
    result = await _block().process({"operation": "frobnicate"})

    assert result["status"] == "error"
    assert result["error"] == (
        "Unknown operation: frobnicate. Use: record_correction, tune, "
        "promote, status, reset"
    )
    assert "tier_level" not in result


async def test_process_refuses_a_correction_with_no_formula_id():
    result = await _block().process({
        "operation": "record_correction",
        "correction_data": {"predicted": 100, "actual": 110},
    })

    assert result["status"] == "error"
    assert result["error"] == "formula_id required"


async def test_process_refuses_a_correction_with_no_measured_actual():
    block = _block()

    result = await block.process({
        "operation": "record_correction",
        "correction_data": {"formula_id": "concrete_cost", "predicted": 100},
    })

    assert result["status"] == "error"
    assert result["error"] == "predicted and actual values required"
    # And nothing was recorded for it.
    status = await block.process({"operation": "status"})
    assert status["total_formulas"] == 0


async def test_process_refuses_a_reset_with_no_formula_id():
    result = await _block().process({"operation": "reset"})

    assert result["status"] == "error"
    assert result["error"] == "formula_id required for reset"


async def test_process_defaults_to_status_when_handed_nothing():
    """A bare call is a status query over an empty store -- not a recorded
    correction with invented numbers."""
    result = await _block().process({})

    assert result["status"] == "success"
    assert result["total_formulas"] == 0
    assert result["tier_distribution"] == {}
    assert result["formula_summary"] == {}


async def test_execute_carries_the_payload_process_computed():
    block = _block()
    for predicted in (100.0, 250.0, 400.0, 1000.0, 2500.0):
        await _record(block, "concrete_cost", predicted, predicted * 1.10)

    envelope = await block.execute({"operation": "status"})

    assert envelope["block"] == "learning_engine"
    assert envelope["status"] == "success"
    payload = envelope["result"]
    assert payload["total_formulas"] == 1
    assert payload["formula_summary"]["concrete_cost"]["coefficients"][
        "scale"
    ] == pytest.approx(1.10, abs=1e-4)


async def test_execute_reports_error_when_process_refused():
    envelope = await _block().execute({"operation": "frobnicate"})

    assert envelope["status"] == "error"
    assert envelope["confidence"] == 0.0
    assert envelope["result"]["error"].startswith("Unknown operation: frobnicate")
