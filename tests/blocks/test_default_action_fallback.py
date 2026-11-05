"""A block called with no action falls back to its OWN declared default
(ui_schema 'action' default, else first option) instead of answering
'Unknown action: None'. This is the root-cause fix for the stalled
exec-programs build: the workflow block dispatched a child (validation) with
no action, and the child had no way to default it, so it refused with
'Unknown action: None' and the writer burned both rework rounds on a failure
that was never in the code it wrote.
"""
import pytest

from app.core.typed_block import TypedBlock


class _ActionBlock(TypedBlock):
    name = "action_probe"
    version = "1.0"
    ui_schema = {
        "params": [
            {"name": "action", "type": "select",
             "options": ["primary_op", "other_op"], "default": "primary_op"},
        ]
    }

    async def process(self, input_data, params=None):
        action = (params or {}).get("action")
        if action not in ("primary_op", "other_op"):
            return {"status": "error", "error": f"Unknown action: {action}"}
        return {"status": "success", "ran": action}


class _OptionOnlyBlock(TypedBlock):
    name = "option_only"
    version = "1.0"
    ui_schema = {
        "params": [
            {"name": "action", "type": "select", "options": ["first_op", "second_op"]},
        ]
    }

    async def process(self, input_data, params=None):
        action = (params or {}).get("action")
        if action not in ("first_op", "second_op"):
            return {"status": "error", "error": f"Unknown action: {action}"}
        return {"status": "success", "ran": action}


def test_default_action_reads_the_schema_default():
    assert _ActionBlock()._default_action() == "primary_op"


def test_default_action_falls_back_to_first_option_when_no_default():
    assert _OptionOnlyBlock()._default_action() == "first_op"


@pytest.mark.asyncio
async def test_execute_with_no_action_uses_the_blocks_default():
    # The exact failure mode: no action anywhere -> used to be Unknown action: None.
    result = await _ActionBlock().execute({"item": 1}, {})
    assert "Unknown action" not in str(result)
    assert "primary_op" in str(result)


@pytest.mark.asyncio
async def test_execute_first_option_default_for_option_only_block():
    result = await _OptionOnlyBlock().execute({"item": 1}, {})
    assert "Unknown action" not in str(result)
    assert "first_op" in str(result)


@pytest.mark.asyncio
async def test_execute_never_overrides_an_explicit_action():
    result = await _ActionBlock().execute({"item": 1}, {"action": "other_op"})
    assert "Unknown action" not in str(result)
    assert "other_op" in str(result)
