"""MCP Registry — block capability discovery without instantiating blocks.

Schemas live on the CLASS (name, version, description, ui_schema, layer, tags).
Reading them at the class level means we can build the registry without paying
the import-time cost of instantiating every block — which matters because
heavy blocks (sklearn, ifcopenshell, ezdxf) make instantiation expensive.

The registry is the single source of truth for capability discovery used by:
- The agent swarm (filtering tool lists per agent)
- The MCP SSE server (responding to list_tools)
- Anything that needs to ask "what blocks emit tool X" or "which tools have
  tag Y"
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.blocks import BLOCK_REGISTRY


def _build_input_schema_from_class(block_cls: Any) -> Dict[str, Any]:
    """Read ui_schema from the class and turn it into a JSON Schema fragment.

    Mirrors app/mcp_server.py:_build_tool_schema so both the in-process
    registry and the SSE/stdio MCP server agree on what each tool accepts.
    """
    ui_schema = getattr(block_cls, "ui_schema", {}) or {}
    input_cfg = ui_schema.get("input", {}) if isinstance(ui_schema, dict) else {}
    properties: Dict[str, Any] = {}

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
                "description": f"Input data for the {getattr(block_cls, 'name', 'block')} block",
            }
        else:
            properties["input"] = {
                "type": "string",
                "description": f"Input data for the {getattr(block_cls, 'name', 'block')} block",
            }

    properties["params"] = {
        "type": "object",
        "description": (
            "Block parameters (e.g. {'action': '...'}). For containers, 'action' is required."
        ),
        "default": {},
    }

    required = ["input"] if "input" in properties else []
    return {"type": "object", "properties": properties, "required": required}


def _schema_for_class(name: str, block_cls: Any) -> Dict[str, Any]:
    """Build the full per-block schema purely from class attributes."""
    description = getattr(block_cls, "description", "") or f"Execute the {name} block"
    return {
        "name": name,
        "version": getattr(block_cls, "version", "1.0.0"),
        "description": description,
        "metadata": {
            "layer": getattr(block_cls, "layer", 3),
            "tags": list(getattr(block_cls, "tags", []) or []),
            "requires": list(getattr(block_cls, "requires", []) or []),
        },
        "tools": [
            {
                "name": f"{name}_execute",
                "description": description,
                "inputSchema": _build_input_schema_from_class(block_cls),
            }
        ],
    }


class MCPRegistry:
    """Capability registry over BLOCK_REGISTRY. Schemas read from class only."""

    def __init__(self, block_registry: Any) -> None:
        self.block_registry = block_registry
        self._schemas_cache: Dict[str, Dict[str, Any]] = {}

    def get_block_schema(self, block_name: str) -> Dict[str, Any]:
        if block_name in self._schemas_cache:
            return self._schemas_cache[block_name]
        if block_name not in self.block_registry:
            raise ValueError(f"Block '{block_name}' not in registry")
        block_cls = self.block_registry[block_name]
        schema = _schema_for_class(block_name, block_cls)
        self._schemas_cache[block_name] = schema
        return schema

    def get_all_schemas(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for name in self.block_registry.keys():
            try:
                out[name] = self.get_block_schema(name)
            except Exception:
                continue
        return out

    def get_tools_for_block(self, block_name: str) -> List[Dict[str, Any]]:
        return self.get_block_schema(block_name).get("tools", [])

    def find_blocks_with_capability(self, capability: str) -> List[str]:
        return [
            name
            for name, schema in self.get_all_schemas().items()
            if capability in schema.get("metadata", {}).get("tags", [])
        ]

    def get_stats(self) -> Dict[str, Any]:
        schemas = self.get_all_schemas()
        return {
            "total_blocks": len(schemas),
            "total_tools": sum(len(s.get("tools", [])) for s in schemas.values()),
            "blocks_by_layer": self._group_by_layer(schemas),
            "blocks_by_tag": self._group_by_tag(schemas),
        }

    @staticmethod
    def _group_by_layer(schemas: Dict[str, Dict[str, Any]]) -> Dict[int, int]:
        out: Dict[int, int] = {}
        for s in schemas.values():
            layer = s.get("metadata", {}).get("layer", 0)
            out[layer] = out.get(layer, 0) + 1
        return out

    @staticmethod
    def _group_by_tag(schemas: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for s in schemas.values():
            for tag in s.get("metadata", {}).get("tags", []):
                out[tag] = out.get(tag, 0) + 1
        return out


mcp_registry = MCPRegistry(BLOCK_REGISTRY)
