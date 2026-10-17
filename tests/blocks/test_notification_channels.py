"""The MCP channel must work in a standalone (vendored) runtime.

New-shape test for the coupling found live: a factory-built platform's
notification block answered "MCP dispatch failed: No module named
'app.dependencies'" -- the one channel that needs no external service was
the one channel that only worked inside the Blocks platform.
"""

import sys

import pytest

from app.blocks import get_block


@pytest.mark.asyncio
async def test_mcp_channel_survives_a_missing_dependencies_module(monkeypatch):
    """Hide app.dependencies the way a vendored runtime would (it is never
    vendored -- it drags in the whole platform); dispatch must fall back to
    plain construction instead of failing the send."""
    monkeypatch.setitem(sys.modules, "app.dependencies", None)

    block = get_block("notification")()
    envelope = await block.execute(
        {
            "channel": "mcp",
            "message": "attention",
            "block": "analytics",
            "payload": {"metric": "probe", "value": 1},
            "params": {"action": "track_event"},
        },
        {"action": "send"},
    )
    result = envelope.get("result", envelope)
    assert result.get("status") == "success", result
    assert result.get("channel") == "mcp"
    assert result.get("sent") is True
