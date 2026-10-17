"""mcp_adapter: read-only tool catalog, no execution passthrough."""

from __future__ import annotations

import asyncio

from app.blocks.mcp_adapter import MCPAdapterBlock


def _run(block, **data):
    return asyncio.run(block.process(dict(data), params={}))


def test_list_tools_default_action():
    block = MCPAdapterBlock()
    out = _run(block)
    assert out["status"] == "success"
    names = [t["name"] for t in out["tools"]]
    assert "mcp_adapter" not in names, "the adapter must not expose itself"
    assert names, "catalog must not be empty"


def test_list_tools_schema_shape():
    block = MCPAdapterBlock()
    out = _run(block, action="list_tools")
    for tool in out["tools"]:
        assert {"name", "description", "inputSchema"} <= set(tool), tool


def test_describe_known_tool():
    block = MCPAdapterBlock()
    listed = _run(block, action="list_tools")
    first = listed["tools"][0]["name"]
    out = _run(block, action="describe", tool=first)
    assert out["status"] == "success"
    assert out["tool"]["name"] == first


def test_describe_unknown_tool_is_named():
    block = MCPAdapterBlock()
    out = _run(block, action="describe", tool="no_such_tool_xyz")
    assert out["status"] == "error"
    assert "Unknown tool" in out["error"]


def test_unknown_action_is_named():
    block = MCPAdapterBlock()
    out = _run(block, action="invoke_tool")
    assert out["status"] == "error"
    assert "Unknown action" in out["error"]
