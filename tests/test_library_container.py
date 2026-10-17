"""Library Container — backend registry, catalogue, evaluation.

These tests must pass on a slim CI environment where CoolProp and QuantLib
are NOT installed. Backend evaluators that require an absent dep should
return a structured error, never raise.
"""

from __future__ import annotations

import pytest

from app.blocks.library_container import LibraryContainerBlock


@pytest.fixture
def block() -> LibraryContainerBlock:
    return LibraryContainerBlock()


# ── action: list_backends ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_backends_returns_four_entries_with_available_flags(block):
    res = await block.process({}, {"action": "list_backends"})
    assert res["status"] == "success"
    assert res["total"] == 4
    names = {b["name"] for b in res["backends"]}
    assert names == {"sympy", "pint", "coolprop", "quantlib"}
    for entry in res["backends"]:
        assert "available" in entry
        assert isinstance(entry["available"], bool)
        # version is None when missing, str when installed
        assert entry["version"] is None or isinstance(entry["version"], str)


@pytest.mark.asyncio
async def test_list_backends_is_default_action(block):
    """Calling process({}) with no action should default to list_backends."""
    res = await block.process({})
    assert res["status"] == "success"
    assert res["action"] == "list_backends"


# ── action: formula_catalogue ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_formula_catalogue_has_at_least_four_entries(block):
    res = await block.process({}, {"action": "formula_catalogue"})
    assert res["status"] == "success"
    assert res["total"] >= 4
    for f in res["formulas"]:
        assert "name" in f
        assert "backend" in f
        assert "description" in f
        assert f["backend"] in {"sympy", "pint", "coolprop", "quantlib"}


# ── action: evaluate ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluate_sympy_simple_addition(block):
    res = await block.process(
        {},
        {
            "action": "evaluate",
            "backend": "sympy",
            "expression": "a + b",
            "variables": {"a": 1, "b": 2},
        },
    )
    assert res["status"] == "success"
    assert res["backend"] == "sympy"
    # Result should be numeric 3 (or string "3" — accept both).
    assert res["result"] == 3 or res["result"] == 3.0 or str(res["result"]) == "3"


@pytest.mark.asyncio
async def test_evaluate_pint_velocity_quantity(block):
    res = await block.process(
        {},
        {
            "action": "evaluate",
            "backend": "pint",
            "expression": "100 meter / 2 second",
            "variables": {},
        },
    )
    # Pint is a hard requirement (in requirements.txt) so this must succeed.
    assert res["status"] == "success"
    assert res["backend"] == "pint"
    assert res["magnitude"] == pytest.approx(50.0)
    # Dimensionality should be [length] / [time]
    assert "length" in res["dimensionality"] and "time" in res["dimensionality"]


@pytest.mark.asyncio
async def test_evaluate_coolprop_shape_when_missing_or_present(block):
    res = await block.process(
        {},
        {
            "action": "evaluate",
            "backend": "coolprop",
            "expression": "PropsSI('D','T',T,'P',P,'Water')",
            "variables": {"T": 298.15, "P": 101325},
        },
    )
    # Either the package isn't installed (error shape) OR it produced a
    # numeric result — assert SHAPE not value.
    if res["status"] == "error":
        assert res["error"] == "Backend coolprop not installed" or "coolprop" in res["error"].lower()
    else:
        assert res["status"] == "success"
        assert res["backend"] == "coolprop"
        assert "result" in res


@pytest.mark.asyncio
async def test_evaluate_quantlib_shape_when_missing_or_present(block):
    res = await block.process(
        {},
        {
            "action": "evaluate",
            "backend": "quantlib",
            "expression": "quote_value",
            "variables": {"quote_value": 950000.0},
        },
    )
    if res["status"] == "error":
        assert res["error"] == "Backend quantlib not installed" or "quantlib" in res["error"].lower()
    else:
        assert res["status"] == "success"
        assert res["backend"] == "quantlib"
        assert "result" in res


# ── action: errors / unknown ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluate_missing_backend_returns_error(block):
    res = await block.process({}, {"action": "evaluate", "expression": "1+1"})
    assert res["status"] == "error"
    assert "backend" in res["error"].lower()


@pytest.mark.asyncio
async def test_evaluate_missing_expression_returns_error(block):
    res = await block.process({}, {"action": "evaluate", "backend": "sympy"})
    assert res["status"] == "error"
    assert "expression" in res["error"].lower()


@pytest.mark.asyncio
async def test_unknown_action_returns_error(block):
    res = await block.process({}, {"action": "make_coffee"})
    assert res["status"] == "error"
    assert "unknown action" in res["error"].lower()


# ── registration ──────────────────────────────────────────────────────────


def test_block_is_registered_in_registry():
    """The block must be discoverable via BLOCK_REGISTRY (name + class)."""
    from app.blocks import BLOCK_REGISTRY

    assert "library_container" in BLOCK_REGISTRY
    cls = BLOCK_REGISTRY["library_container"]
    assert cls is LibraryContainerBlock
    instance = cls()
    assert instance.name == "library_container"
    assert instance.layer == 4
    assert "library" in instance.tags
    assert "formula" in instance.tags
