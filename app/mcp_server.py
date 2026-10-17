"""
Cerebrum Blocks MCP Server

Exposes all blocks from BLOCK_REGISTRY as MCP tools.

Usage:
    # stdio (default — for the Kimi CLI)
    python -m app.mcp_server

    # SSE (HTTP) transport
    python -m app.mcp_server --transport sse --port 8001

    # Via uvicorn (SSE only)
    uvicorn app.mcp_server:app_sse --port 8001
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, Sequence

# Ensure project root is on path when run as module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from app.blocks import BLOCK_REGISTRY, get_all_blocks
from app.dependencies import _create_block_instance, init_blocks
from app.core.universal_base import UniversalContainer

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("cerebrum-mcp")

# Cache for block instances
_block_cache: Dict[str, Any] = {}


async def _get_block_instance(block_name: str):
    """Get or create a block instance."""
    if block_name not in _block_cache:
        if block_name not in BLOCK_REGISTRY:
            raise ValueError(f"Block '{block_name}' not found")
        _block_cache[block_name] = _create_block_instance(BLOCK_REGISTRY[block_name])
    return _block_cache[block_name]


def _build_tool_schema(block_name: str, block_class) -> Dict[str, Any]:
    """Build JSON Schema for a block tool from ui_schema or generic fallback."""
    ui_schema = getattr(block_class, "ui_schema", {})
    input_cfg = ui_schema.get("input", {})
    properties: Dict[str, Any] = {}

    # If ui_schema describes structured input fields, expose them
    fields = input_cfg.get("fields", []) if isinstance(input_cfg, dict) else []
    if fields:
        for field in fields:
            if not isinstance(field, dict):
                continue
            fname = field.get("name")
            if not fname:
                continue
            ftype = field.get("type", "string")
            prop: Dict[str, Any] = {"description": field.get("label", fname)}
            if ftype in ("number", "float", "int", "integer"):
                prop["type"] = "number"
            elif ftype in ("bool", "boolean"):
                prop["type"] = "boolean"
            elif ftype in ("object", "json", "dict"):
                prop["type"] = "object"
            elif ftype in ("array", "list"):
                prop["type"] = "array"
            else:
                prop["type"] = "string"
            properties[fname] = prop
    else:
        input_type = input_cfg.get("type", "text") if isinstance(input_cfg, dict) else "text"
        if input_type in ("json", "object"):
            properties["input"] = {
                "type": "object",
                "description": f"Input data for the {block_name} block",
            }
        else:
            properties["input"] = {
                "type": "string",
                "description": f"Input data for the {block_name} block (text, URL, etc.)",
            }

    # Every block also accepts params
    properties["params"] = {
        "type": "object",
        "description": (
            f"Block parameters (e.g. {{'action': '...'}}). "
            f"For containers, 'action' is usually required."
        ),
        "default": {},
    }

    required = []
    if "input" in properties:
        required.append("input")

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def _make_tool_name(block_name: str) -> str:
    """Sanitize block name for MCP tool naming rules."""
    # MCP tool names should match ^[a-zA-Z0-9_-]{1,64}$
    sanitized = block_name.replace("_", "-").lower()
    return f"cerebrum-{sanitized}"


def _parse_tool_name(tool_name: str) -> str:
    """Reverse _make_tool_name to get block name."""
    if not tool_name.startswith("cerebrum-"):
        raise ValueError(f"Invalid tool name: {tool_name}")
    raw = tool_name[len("cerebrum-"):]
    return raw.replace("-", "_")


# ---------------------------------------------------------------------------
# MCP Server Setup
#
# mcp 2.x removed the decorator registration API (`@server.list_tools()` /
# `@server.call_tool()`) from the low-level Server; handlers are now passed
# to the constructor as `on_list_tools=` / `on_call_tool=` callables with a
# `(ctx, params)` signature returning typed results. Booting the old
# decorator code under mcp 2.0.0 raised `AttributeError: 'Server' object
# has no attribute 'list_tools'` and the /mcp mount silently disappeared.
# ---------------------------------------------------------------------------


def _build_tools() -> list[Tool]:
    """Expose every block in BLOCK_REGISTRY as an MCP tool."""
    tools: list[Tool] = []

    for name, block_class in get_all_blocks().items():
        description = getattr(block_class, "description", "")
        if not description:
            description = f"Execute the {name} block from Cerebrum Blocks"

        # Append tags/layer info for richer context
        tags = getattr(block_class, "tags", [])
        layer = getattr(block_class, "layer", 3)
        extra_meta = []
        if tags:
            extra_meta.append(f"tags: {', '.join(tags)}")
        extra_meta.append(f"layer: {layer}")
        description = f"{description} ({'; '.join(extra_meta)})"

        schema = _build_tool_schema(name, block_class)
        tool_name = _make_tool_name(name)

        tools.append(
            Tool(
                name=tool_name,
                description=description,
                inputSchema=schema,
            )
        )

    # Chain tool
    tools.append(
        Tool(
            name="cerebrum-chain",
            description=(
                "Execute a chain of Cerebrum blocks in sequence. "
                "Each step runs the output of the previous step into the next block."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "description": (
                            "List of steps. Each step is an object with "
                            "'block' (str) and 'params' (object)."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "block": {"type": "string"},
                                "params": {"type": "object"},
                                "input_mapping": {"type": "object"},
                            },
                            "required": ["block"],
                        },
                    },
                    "initial_input": {
                        "type": "string",
                        "description": "Starting input for the first step",
                        "default": "",
                    },
                },
                "required": ["steps"],
            },
        )
    )

    return tools


async def _on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
    """mcp 2.x list-tools handler."""
    return types.ListToolsResult(tools=_build_tools())


async def _on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
    """mcp 2.x call-tool handler: unwrap params, wrap content into a result."""
    content = await _dispatch_tool(params.name, params.arguments)
    is_error = any(
        isinstance(item, TextContent) and item.text.startswith(("Error", "Unknown tool:"))
        for item in content
    )
    return types.CallToolResult(content=list(content), isError=is_error)


async def _dispatch_tool(name: str, arguments: Any) -> Sequence[TextContent]:
    """Route MCP tool calls to block execution."""
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return [
            TextContent(
                type="text",
                text=f"Error: arguments must be an object, got {type(arguments).__name__}",
            )
        ]

    # --- cerebrum-chain ---
    if name == "cerebrum-chain":
        return await _handle_chain(arguments)

    # --- single block ---
    try:
        block_name = _parse_tool_name(name)
    except ValueError:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    if block_name not in BLOCK_REGISTRY:
        return [TextContent(type="text", text=f"Block '{block_name}' not found in registry.")]

    try:
        block = await _get_block_instance(block_name)

        # Extract input / params from arguments
        # If the schema had structured fields, they will be in arguments directly.
        # Otherwise expect 'input' and 'params'.
        ui_schema = getattr(BLOCK_REGISTRY[block_name], "ui_schema", {})
        input_fields = ui_schema.get("input", {}).get("fields", []) if isinstance(ui_schema.get("input"), dict) else []

        if input_fields:
            # Structured input: pass the whole arguments dict minus 'params' as input
            params = arguments.get("params", {})
            input_data = {k: v for k, v in arguments.items() if k != "params"}
        else:
            input_data = arguments.get("input", "")
            params = arguments.get("params", {})

        result = await block.execute(input_data, params)
        text = json.dumps(result, indent=2, default=str)
        return [TextContent(type="text", text=text)]

    except Exception as e:
        logger.exception("Block execution failed for %s", block_name)
        return [TextContent(type="text", text=f"Error executing {block_name}: {str(e)}")]


async def _handle_chain(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Execute a block chain via the orchestrator."""
    steps = arguments.get("steps", [])
    initial_input = arguments.get("initial_input", "")

    if not steps:
        return [TextContent(type="text", text="Error: 'steps' array is required for chaining.")]

    if "orchestrator" not in BLOCK_REGISTRY:
        return [TextContent(type="text", text="Error: orchestrator block not available for chaining.")]

    try:
        orchestrator = await _get_block_instance("orchestrator")
        result = await orchestrator.execute(
            initial_input,
            {"steps": steps, "fail_fast": True, "continue_on_error": False},
        )
        text = json.dumps(result, indent=2, default=str)
        return [TextContent(type="text", text=text)]
    except Exception as e:
        logger.exception("Chain execution failed")
        return [TextContent(type="text", text=f"Error executing chain: {str(e)}")]


server = Server(
    "cerebrum-blocks",
    version="2.0.0",
    on_list_tools=_on_list_tools,
    on_call_tool=_on_call_tool,
)


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

async def run_stdio():
    """Run MCP server over stdio (default)."""
    await init_blocks()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


# ---------------------------------------------------------------------------
# Optional SSE app for HTTP transport
# ---------------------------------------------------------------------------

from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route

_sse_transport = SseServerTransport("/messages/")


class _SseEndpoint:
    """ASGI app wrapper for SSE transport."""

    async def __call__(self, scope, receive, send):
        await init_blocks()
        async with _sse_transport.connect_sse(
            scope, receive, send
        ) as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )


class _MessageEndpoint:
    """ASGI app wrapper for SSE message POST endpoint."""

    async def __call__(self, scope, receive, send):
        await _sse_transport.handle_post_message(scope, receive, send)


app_sse = Starlette(
    debug=True,
    routes=[
        Route("/sse", endpoint=_SseEndpoint()),
        Route("/messages/", endpoint=_MessageEndpoint(), methods=["POST"]),
    ],
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Cerebrum Blocks MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host for SSE transport")
    parser.add_argument("--port", type=int, default=8001, help="Port for SSE transport")
    args = parser.parse_args()

    if args.transport == "stdio":
        asyncio.run(run_stdio())
    else:
        import uvicorn
        uvicorn.run(app_sse, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
