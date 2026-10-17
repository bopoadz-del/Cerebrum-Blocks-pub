"""Pint validation â€” ported The_Fork app/blocks/validation_pipeline.py.

Five-stage (syntactic / dimensional / physical / empirical / operational)
numeric validation with Pint dimensional analysis and file-backed
empirical ranges. Tests are ported from The_Fork
tests/test_validation_pipeline.py and adapted to the Store's envelope.
"""
from __future__ import annotations

import asyncio

import pytest

from app.blocks.pint_validation import PintValidationBlock


@pytest.fixture
def block():
    return PintValidationBlock()


def _run(coro):
    return asyncio.run(coro)


async def _process(block, payload):
    result = await block.process(payload)
    assert result.get("status") == "success"
    return result


def _stage(result, name):
    return result["stages"][name]


# -- stage 1: syntactic -----------------------------------------------------

def test_syntactic_none_fails_and_short_circuits(block):
    result = _run(_process(block, {"value": None, "context": {"metric": "temperature_degc"}}))
    assert result["overall"] == "fail"
    assert result["first_failure"] == "syntactic"
    assert "skipped" in _stage(result, "physical")["reason"]


def test_syntactic_non_numeric_string_fails(block):
    result = _run(_process(block, {"value": "hello"}))
    assert result["first_failure"] == "syntactic"


def test_syntactic_nan_and_inf_fail(block):
    assert _run(_process(block, {"value": float("nan")}))["first_failure"] == "syntactic"
    assert _run(_process(block, {"value": float("inf")}))["first_failure"] == "syntactic"


def test_syntactic_string_numeric_coerces(block):
    result = _run(_process(block, {"value": "  42.5 ", "context": {"metric": "temperature_degc"}}))
    assert result["value"] == 42.5


def test_prose_claim_runs_physical_and_fails(block):
    """Leftover-hat L4: worded 40 m span on a 50 mm steel section fails Physical."""
    result = _run(_process(block, {
        "value": None,
        "claim": (
            "forty metres span on a fifty millimetre steel section "
            "with eight hundred kilonewtons per metre"
        ),
    }))
    assert _stage(result, "syntactic")["pass"] is True
    assert _stage(result, "physical")["pass"] is False
    assert result["first_failure"] == "physical"
    assert result.get("tier") == 4


# -- stage 2: dimensional (Pint) ---------------------------------------------

def test_dimensional_unrecognised_unit_fails(block):
    result = _run(_process(block, {"value": 5.9, "unit": "gibberish_unit"}))
    assert _stage(result, "dimensional")["pass"] is False
    assert result["first_failure"] == "dimensional"


def test_dimensional_construction_shorthand_m3_parses(block):
    result = _run(_process(block, {"value": 5.9, "unit": "m3", "context": {"material_type": "concrete"}}))
    assert _stage(result, "dimensional")["pass"] is True
    assert result["metric_inferred"] == "volume_m3"


def test_dimensional_currency_unit_stripped(block):
    result = _run(_process(block, {"value": 100, "unit": "USD/m3", "context": {"material_type": "concrete"}}))
    assert _stage(result, "dimensional")["pass"] is True


def test_dimensional_degC_offset_parsed(block):
    result = _run(_process(block, {"value": 5.9, "unit": "degC", "context": {"material_type": "concrete"}}))
    assert _stage(result, "dimensional")["pass"] is True


# -- stage 3: physical --------------------------------------------------------

def test_physical_negative_volume_fails(block):
    result = _run(_process(block, {"value": -1, "context": {"metric": "volume_m3", "material_type": "concrete"}}))
    assert _stage(result, "physical")["pass"] is False
    assert "below physical_min" in _stage(result, "physical")["reason"]


def test_physical_negative_temperature_allowed(block):
    result = _run(_process(block, {"value": -20, "unit": "degC", "context": {"material_type": "concrete"}}))
    assert _stage(result, "physical")["pass"] is True


# -- stage 4: empirical (file-backed ranges) ---------------------------------

def test_empirical_concrete_rate_in_range_passes(block):
    result = _run(_process(block, {
        "value": 200,
        "unit": "USD/m3",
        "context": {"material_type": "concrete", "metric": "rate_usd_per_m3"},
    }))
    assert _stage(result, "empirical")["pass"] is True


def test_empirical_out_of_range_fails(block):
    result = _run(_process(block, {
        "value": 1_000_000,
        "unit": "USD/m3",
        "context": {"material_type": "concrete", "metric": "rate_usd_per_m3"},
    }))
    assert _stage(result, "empirical")["pass"] is False
    assert result["first_failure"] == "empirical"


def test_empirical_borderline_flag_and_strict_mode(block):
    result = _run(_process(block, {
        "value": 700,
        "unit": "USD/m3",
        "context": {"material_type": "concrete", "metric": "rate_usd_per_m3"},
    }))
    assert _stage(result, "empirical")["pass"] is True
    assert result.get("borderline") is True

    strict = _run(_process(block, {
        "value": 700,
        "unit": "USD/m3",
        "context": {"material_type": "concrete", "metric": "rate_usd_per_m3", "strict": True},
    }))
    assert _stage(strict, "empirical")["pass"] is False
    assert "strict" in _stage(strict, "empirical")["reason"]


# -- the donor's own regression -------------------------------------------------

def test_5900_degc_delta_fails_empirical(block):
    """The NumPy code-gen bug that motivated this block: 5,900 Â°C vs 5.9 Â°C."""
    result = _run(_process(block, {"value": 5900.0, "unit": "delta_degC", "context": {"metric": "temperature_degc"}}))
    assert result["overall"] == "fail"
    assert result["first_failure"] == "empirical"


# -- envelope + refusal --------------------------------------------------------

def test_empty_input_is_an_error_envelope(block):
    r = _run(block.execute({}))
    assert r["block_id"] == "pint_validation"
    assert r["status"] == "error"
    assert "Provide" in r["error"]


def test_execute_wraps_success_as_ok_envelope(block):
    r = _run(block.execute({"value": 5.9, "unit": "delta_degC", "context": {"metric": "temperature_degc"}}))
    assert r["status"] == "ok"
    assert r["result"]["overall"] == "pass"
    assert r["result"]["stages"]["dimensional"]["pass"] is True
