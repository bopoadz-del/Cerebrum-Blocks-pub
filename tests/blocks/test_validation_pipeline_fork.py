"""Validation pipeline tests - ported behavior from The_Fork validation_pipeline_fork."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.validation_pipeline_fork import ValidationPipelineForkBlock


def _run(coro):
    return asyncio.run(coro)


def _validate(payload):
    b = ValidationPipelineForkBlock()
    return _run(b.process(payload))


def test_clean_numeric_value_passes_all_stages():
    r = _validate({"value": 250, "unit": "USD/m3",
                   "context": {"material_type": "concrete", "metric": "rate_usd_per_m3", "currency": "USD"}})
    assert r["status"] == "ok"
    assert r["result"]["overall"] == "pass"
    assert all(s["pass"] for s in r["result"]["stages"].values())


def test_no_input_is_refused():
    b = ValidationPipelineForkBlock()
    r = _run(b.process({}))
    assert r["status"] == "refused"
    assert "Provide" in r["error"]


def test_bool_value_fails_syntactic():
    r = _validate({"value": True})
    assert r["status"] == "failed"
    assert r["result"]["first_failure"] == "syntactic"
    assert "bool" in r["result"]["stages"]["syntactic"]["reason"]


def test_non_numeric_value_fails_syntactic():
    r = _validate({"value": "not-a-number"})
    assert r["status"] == "failed"
    assert r["result"]["first_failure"] == "syntactic"


def test_unrecognised_unit_fails_dimensional():
    r = _validate({"value": 5.9, "unit": "furlongs_per_fortnight"})
    assert r["status"] == "failed"
    assert r["result"]["stages"]["dimensional"]["pass"] is False
    assert "not recognised" in r["result"]["stages"]["dimensional"]["reason"]


def test_degc_delta_carveout_passes_dimensional():
    r = _validate({"value": 5.9, "unit": "degC",
                   "context": {"metric": "temperature_degc"}})
    assert r["result"]["stages"]["dimensional"]["pass"] is True


def test_negative_value_fails_physical_by_default():
    r = _validate({"value": -10, "unit": "m"})
    assert r["status"] == "failed"
    assert r["result"]["stages"]["physical"]["pass"] is False


def test_far_above_empirical_range_fails():
    r = _validate({"value": 999999, "unit": "USD/m3",
                   "context": {"material_type": "concrete", "metric": "rate_usd_per_m3",
                               "currency": "USD", "strict": True}})
    assert r["status"] == "failed"
    assert r["result"]["stages"]["empirical"]["pass"] is False
    assert "strict" in r["result"]["stages"]["empirical"]["reason"]


def test_operational_duration_exceeding_available_fails():
    r = _validate({"value": 16, "unit": "weeks",
                   "context": {"metric": "duration_weeks", "duration_weeks": 16, "available_weeks": 8}})
    assert r["status"] == "failed"
    assert r["result"]["stages"]["operational"]["pass"] is False
    assert "exceeds available" in r["result"]["stages"]["operational"]["reason"]


def test_span_depth_claim_flag_is_caught():
    # Leftover-hat L4: 40 m span on a 50 mm section is not a real beam.
    r = _validate({"claim": "A 40 m floor span on a 50 mm steel I-section carries the roof."})
    assert r["result"]["overall"] == "fail"
    assert r["result"]["first_failure"] == "physical"
    assert "span/depth" in r["result"]["stages"]["physical"]["reason"]


def test_empirical_ranges_file_is_loaded():
    from app.blocks.validation_pipeline_fork import _load_ranges, _lookup_range

    ranges = _load_ranges()
    assert "concrete.rate_usd_per_m3.USD" in ranges
    assert _lookup_range("concrete", "rate_usd_per_m3", "USD") == (50.0, 500.0)
    assert _lookup_range("concrete", "rate_usd_per_m3", "SAR") == (188.0, 1875.0)


def test_envelope_block_id_present():
    b = ValidationPipelineForkBlock()
    r = _run(b.process({"action": "whatever", "value": 1, "unit": "m"}))
    # The pipeline ignores unknown actions and validates the value.
    assert r["block_id"] == "validation_pipeline_fork"


def test_unknown_metric_empirical_is_skipped_not_failed():
    r = _validate({"value": 42, "unit": "m",
                   "context": {"material_type": "no_such_material", "metric": "no_such_metric"}})
    assert r["result"]["stages"]["empirical"]["pass"] is True
    assert "skipped" in r["result"]["stages"]["empirical"]["reason"]
