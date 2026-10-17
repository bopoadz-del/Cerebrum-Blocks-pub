"""Pint unit-validation regression — wires `_validate_units` to Pint.

Pre-fix behaviour: `_validate_units` returned a stub `{value, unit, formatted}`
with no dimensional check. After the fix it should:
  - parse {value, unit} as a Pint quantity;
  - detect a target unit from the description text (e.g. "m³");
  - return unit_check ∈ {ok, mismatch, no_target, skipped} with metadata.
"""

from __future__ import annotations

import pytest

from app.blocks.formula_executor import FormulaExecutorBlock


@pytest.fixture
def block() -> FormulaExecutorBlock:
    return FormulaExecutorBlock()


def test_validate_units_ok_volume_in_m3(block):
    """Result m³ vs target m³ (from 'compute volume in m³') — exact match."""
    out = block._validate_units(
        {"value": 100, "unit": "m3"},
        {},
        "compute volume in m³",
    )
    assert out["unit_check"] == "ok"
    assert out["result_in_target"] == 100.0


def test_validate_units_mismatch_volume_vs_area(block):
    """Result m³ vs target m² (from 'compute area in m²') — dimensional mismatch."""
    out = block._validate_units(
        {"value": 100, "unit": "m3"},
        {},
        "compute area in m²",
    )
    assert out["unit_check"] == "mismatch"
    assert out["result_in_target"] is None


def test_validate_units_currency_match(block):
    out = block._validate_units(
        {"value": 5000, "unit": "USD"},
        {},
        "estimated cost in USD",
    )
    assert out["unit_check"] == "ok"
    assert out["result_in_target"] == 5000.0


def test_validate_units_currency_mismatch(block):
    out = block._validate_units(
        {"value": 5000, "unit": "SAR"},
        {},
        "estimated cost in USD",
    )
    assert out["unit_check"] == "mismatch"


def test_validate_units_no_target_in_description(block):
    """No recognisable unit token in the description → no_target."""
    out = block._validate_units(
        {"value": 100, "unit": "m3"},
        {},
        "compute the thing",
    )
    assert out["unit_check"] == "no_target"


def test_validate_units_skipped_for_non_quantity_result(block):
    """Raw scalar (legacy result shape) gets a `skipped` verdict, not a crash."""
    out = block._validate_units(42.0, {}, "compute volume in m³")
    assert out["unit_check"] == "skipped"
