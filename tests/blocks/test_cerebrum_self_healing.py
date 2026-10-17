"""Real-behavior tests for the Cerebrum self-healing state machine block."""

import pytest

from app.blocks.cerebrum_self_healing import CerebrumSelfHealingBlock


@pytest.mark.asyncio
async def test_layers_expose_hotswap_and_healing():
    block = CerebrumSelfHealingBlock()
    env = await block.execute({"action": "layers"})
    assert env["status"] == "ok"
    layers = env["result"]["layers"]
    assert len(layers) == 14
    assert "hotswap" in layers and "healing" in layers


@pytest.mark.asyncio
async def test_actions_include_heal_error():
    block = CerebrumSelfHealingBlock()
    env = await block.execute({"action": "actions"})
    assert env["status"] == "ok"
    assert "heal_error" in env["result"]["actions"]


@pytest.mark.asyncio
async def test_move_layer_is_deterministic_transition():
    block = CerebrumSelfHealingBlock()
    env = await block.execute({"action": "move_layer", "to": "healing"})
    assert env["status"] == "ok"
    body = env["result"]
    assert body["success"] is True
    assert body["layer"] == "healing"
    assert body["data"] == {"previous_layer": "coding", "current_layer": "healing"}
    assert body["message"] == "Moved from coding to healing"


@pytest.mark.asyncio
async def test_move_layer_unknown_layer_refused():
    block = CerebrumSelfHealingBlock()
    env = await block.execute({"action": "move_layer", "to": "made_up_layer"})
    assert env["status"] == "refused"
    assert "unknown layer" in env["error"]
    assert block.current_layer == "coding"  # unchanged on refusal


@pytest.mark.asyncio
async def test_handle_error_without_patch_refuses():
    block = CerebrumSelfHealingBlock()
    env = await block.execute({
        "action": "handle_error",
        "error_event": {"event_id": "evt-1", "error_type": "ValueError"},
        "original_code": "x = int('nope')",
    })
    assert env["status"] == "refused"
    assert "patch generation unavailable" in env["error"]


@pytest.mark.asyncio
async def test_handle_error_failed_patch_stays_unhealed():
    block = CerebrumSelfHealingBlock()
    env = await block.execute({
        "action": "handle_error",
        "error_event": {"event_id": "evt-2"},
        "patch": {"success": False, "confidence": 0.9},
    })
    assert env["status"] == "ok"
    body = env["result"]
    assert body["healed"] is False
    assert body["message"] == "Failed to generate patch"


@pytest.mark.asyncio
async def test_handle_error_patch_below_threshold_stays_unhealed():
    block = CerebrumSelfHealingBlock()
    env = await block.execute({
        "action": "handle_error",
        "error_event": {"event_id": "evt-3"},
        "patch": {"success": True, "confidence": 0.5, "patch_id": "p-1"},
    })
    assert env["status"] == "ok"
    body = env["result"]
    assert body["healed"] is False
    assert "below threshold" in body["message"]


@pytest.mark.asyncio
async def test_handle_error_high_confidence_heals_without_auto_apply():
    block = CerebrumSelfHealingBlock()
    env = await block.execute({
        "action": "handle_error",
        "error_event": {"event_id": "evt-4"},
        "patch": {"success": True, "confidence": 0.95, "patch_id": "p-2"},
        "auto_apply": True,
    })
    assert env["status"] == "ok"
    body = env["result"]
    assert body["healed"] is True
    assert body["applied"] is False  # auto-heal default OFF
    assert body["message"] == "Patch generated, awaiting approval"


@pytest.mark.asyncio
async def test_auto_heal_applies_only_when_enabled_and_requested():
    block = CerebrumSelfHealingBlock()
    await block.execute({"action": "enable_auto_heal", "enabled": True})
    env = await block.execute({
        "action": "handle_error",
        "error_event": {"event_id": "evt-5"},
        "patch": {"success": True, "confidence": 0.9, "patch_id": "p-3"},
        "auto_apply": True,
    })
    body = env["result"]
    assert body["healed"] is True
    assert body["applied"] is True
    assert body["message"] == "Patch auto-applied"
    hist = await block.execute({"action": "healing_history"})
    assert hist["result"]["history"][-1]["patch_id"] == "p-3"


@pytest.mark.asyncio
async def test_heal_error_stub_not_ported_as_success():
    block = CerebrumSelfHealingBlock()
    env = await block.execute({"action": "heal_error", "error_logs": "boom"})
    assert env["status"] == "refused"
    assert "stub in the donor" in env["error"]


@pytest.mark.asyncio
async def test_confidence_threshold_clamps():
    block = CerebrumSelfHealingBlock()
    env = await block.execute({"action": "set_confidence_threshold", "threshold": 3.0})
    assert env["result"]["confidence_threshold"] == 1.0
    env = await block.execute({"action": "set_confidence_threshold", "threshold": -1.0})
    assert env["result"]["confidence_threshold"] == 0.0


@pytest.mark.asyncio
async def test_unknown_action_is_error_envelope():
    block = CerebrumSelfHealingBlock()
    env = await block.execute({"action": "nope"})
    assert env["status"] == "error"
    assert "unknown action" in env["error"]
