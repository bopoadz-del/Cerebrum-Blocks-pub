"""Tests for the 5-Stage Validation Pipeline on `app/blocks/validation.py`."""

from __future__ import annotations

import pytest

from app.blocks.validation import ValidationBlock


# ── helpers ─────────────────────────────────────────────────────────────


def _make_block():
    return ValidationBlock(hal_block=None, config={})


def _well_formed_item():
    return {
        "id": "boq-line-001",
        "type": "concrete_pour",
        "value": 120.0,
        "unit": "m3",
        "volume_m3": 120.0,
        "concrete_grade": "C30",
        "rebar_kg": 18000.0,   # 150 kg/m³ — well within plausible.
        "duration_days": 12,
        "cost": 50000.0,
    }


def _by_stage(stages):
    return {s["stage"]: s for s in stages}


# ── happy path ──────────────────────────────────────────────────────────


def test_pipeline_runs_all_five_stages_on_well_formed_item():
    block = _make_block()
    item = _well_formed_item()
    out = block.validate_pipeline(item, context={})
    assert out["status"] in ("ok", "skipped")  # empirical likely skipped
    stages = _by_stage(out["stages"])
    # All 5 stages present, in correct order.
    assert [s["stage"] for s in out["stages"]] == [
        "syntactic", "dimensional", "physical", "empirical", "operational",
    ]
    # Each stage produces one of the expected statuses.
    for name in ("syntactic", "dimensional", "physical", "operational"):
        assert stages[name]["status"] in ("ok", "warn"), (
            f"{name}: {stages[name]}"
        )
    # Empirical stage skipped because no historical_benchmark dep is wired.
    assert stages["empirical"]["status"] == "skipped"
    assert out["fail_fast_stage"] is None


# ── syntactic failure short-circuits when fail_fast=True ────────────────


def test_syntactic_failure_stops_pipeline_when_fail_fast_true():
    block = _make_block()
    bad = {"value": 10}  # missing required `id` and `type`
    out = block.validate_pipeline(bad, context={}, fail_fast=True)
    assert out["status"] == "fail"
    assert out["fail_fast_stage"] == "syntactic"
    stages = _by_stage(out["stages"])
    assert stages["syntactic"]["status"] == "fail"
    # Subsequent stages must be skipped (with a fail_fast reason).
    for name in ("dimensional", "physical", "empirical", "operational"):
        assert stages[name]["status"] == "skipped", f"{name} should be skipped"
        assert stages[name]["details"].get("reason") == "fail_fast"


# ── empirical stage skipped when no benchmark dep ───────────────────────


def test_empirical_stage_skipped_without_benchmark_dep():
    block = _make_block()
    # No historical_benchmark wired → must report skipped, never fail.
    out = block.validate_pipeline(_well_formed_item(), context={})
    stages = _by_stage(out["stages"])
    assert stages["empirical"]["status"] == "skipped"
    assert "historical_benchmark" in stages["empirical"]["details"].get("reason", "")


# ── empirical stage runs against an injected benchmark ──────────────────


def test_empirical_stage_uses_injected_benchmark():
    """Inject a tiny benchmark and prove the 3σ rule fires."""
    block = _make_block()
    # Inject the dep via the wire() hook the resolver checks first.
    block.wire("historical_benchmark", {
        "concrete_pour": {"mean": 100.0, "std": 5.0},  # well-shaped stats
    })

    # 5σ above mean: must fail empirical stage.
    item = _well_formed_item()
    item["value"] = 125.0  # (125 - 100) / 5 = 5σ
    out = block.validate_pipeline(item, context={}, fail_fast=False)
    stages = _by_stage(out["stages"])
    assert stages["empirical"]["status"] == "fail"
    assert stages["empirical"]["details"]["z_score"] >= 3.0


# ── aggregate status bubbles up the worst stage ─────────────────────────


def test_aggregate_status_bubbles_up_worst_stage():
    block = _make_block()
    # Operational fails (cost > budget); other stages are ok/skipped.
    item = _well_formed_item()
    out = block.validate_pipeline(
        item,
        context={"budget": 1000.0},  # cost=50000 dwarfs budget
        fail_fast=False,
    )
    stages = _by_stage(out["stages"])
    assert stages["operational"]["status"] == "fail"
    # Pipeline aggregate must reflect the worst, regardless of earlier OK.
    assert out["status"] == "fail"
    assert out["fail_fast_stage"] == "operational"


# ── fail_fast=False runs all stages even after a failure ────────────────


def test_fail_fast_false_runs_all_stages_after_failure():
    block = _make_block()
    # Physical-stage failure: negative volume.
    item = _well_formed_item()
    item["volume_m3"] = -1.0
    out = block.validate_pipeline(item, context={}, fail_fast=False)

    # All five stages present and none "skipped" with fail_fast reason.
    stages = _by_stage(out["stages"])
    assert set(stages.keys()) == {
        "syntactic", "dimensional", "physical", "empirical", "operational",
    }
    for name, st in stages.items():
        assert st["details"].get("reason") != "fail_fast", f"{name} skipped early"

    # Physical stage flags the failure; pipeline aggregate is fail.
    assert stages["physical"]["status"] == "fail"
    assert out["status"] == "fail"
    assert out["fail_fast_stage"] == "physical"


# ── process() dispatch keeps the action usable from the platform ────────


@pytest.mark.asyncio
async def test_process_dispatches_validate_pipeline_action():
    block = _make_block()
    out = await block.process(
        {"item": _well_formed_item(), "context": {}},
        {"action": "validate_pipeline", "fail_fast": True},
    )
    assert "stages" in out
    assert [s["stage"] for s in out["stages"]] == [
        "syntactic", "dimensional", "physical", "empirical", "operational",
    ]


# ── physical stage catches plausibility issues ──────────────────────────


def test_physical_stage_flags_unsupported_concrete_grade():
    block = _make_block()
    item = _well_formed_item()
    item["concrete_grade"] = "C99"  # not a recognised grade
    res = block._stage_physical(item, {})
    assert res["status"] == "fail"
    assert any("concrete grade" in m for m in res["issues"])


def test_physical_stage_flags_implausible_rebar_ratio():
    block = _make_block()
    item = _well_formed_item()
    item["rebar_kg"] = 999_999.0  # absurd ratio
    res = block._stage_physical(item, {})
    assert res["status"] == "fail"
    assert any("rebar" in m or "ratio" in m for m in res["issues"])
