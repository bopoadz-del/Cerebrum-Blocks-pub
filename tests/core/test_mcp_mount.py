"""The /mcp SSE mount must survive the mcp 2.x API migration.

mcp 2.0.0 removed the decorator registration API from the low-level
``Server`` (``@server.list_tools()`` / ``@server.call_tool()``); handlers
are constructor arguments now. Under the old code, importing
``app.mcp_server`` raised ``AttributeError: 'Server' object has no
attribute 'list_tools'``, ``app/main.py`` swallowed it into an ERROR log
("MCP server not mounted"), and /mcp silently vanished from production.

These tests pin the migrated shape: the mount exists on the real app and
is auth-gated (401, never 404), building the mount emits no ERROR-level
log, and the 2.x handlers still expose every registry block plus the
cerebrum-chain tool.
"""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

import pytest


def test_mcp_mount_is_present_and_auth_gated():
    """/mcp must be mounted and must answer 401 unauthenticated.

    404 here is the regression signature: it means the try/except in
    app/main.py ate an import-time failure and dropped the mount.
    """
    from app.main import app

    assert any(getattr(route, "path", None) == "/mcp" for route in app.routes), (
        "/mcp mount missing from app.routes — the MCP server failed to import"
    )

    with TestClient(app) as client:
        resp = client.get("/mcp/sse")
        assert resp.status_code == 401, (
            f"expected auth-gated 401 from /mcp/sse, got {resp.status_code}"
        )


def test_mcp_mount_construction_emits_no_error_log(caplog):
    """Rebuilding the exact mount from app/main.py must not raise or log ERROR."""
    from fastapi import FastAPI

    with caplog.at_level(logging.ERROR):
        from app.core.security import asgi_auth_required
        from app.mcp_server import app_sse

        scratch_app = FastAPI()
        scratch_app.mount("/mcp", asgi_auth_required(app_sse))

    mcp_errors = [
        rec for rec in caplog.records
        if rec.levelno >= logging.ERROR and "MCP" in rec.getMessage()
    ]
    assert not mcp_errors, f"MCP mount produced ERROR logs: {mcp_errors}"


@pytest.mark.asyncio
async def test_mcp_2x_handlers_expose_blocks_and_chain_tool():
    """The 2.x on_list_tools handler must expose registry blocks + chain."""
    from app.blocks import get_all_blocks
    from app.mcp_server import _make_tool_name, _on_list_tools

    result = await _on_list_tools(None, None)
    tool_names = {tool.name for tool in result.tools}

    assert "cerebrum-chain" in tool_names
    for block_name in get_all_blocks():
        assert _make_tool_name(block_name) in tool_names, (
            f"block '{block_name}' missing from MCP tool listing"
        )
    # Every tool carries an input schema the client can render.
    assert all(tool.input_schema for tool in result.tools)


@pytest.mark.asyncio
async def test_mcp_2x_call_tool_returns_typed_error_result():
    """Unknown tools come back as a typed CallToolResult, not an exception."""
    from mcp.types import CallToolRequestParams

    from app.mcp_server import _on_call_tool

    result = await _on_call_tool(
        None, CallToolRequestParams(name="not-a-cerebrum-tool", arguments={})
    )
    assert result.is_error
    assert result.content and "Unknown tool" in result.content[0].text
