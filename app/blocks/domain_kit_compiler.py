"""Domain Kit Compiler — YAML-sheet semantics to block definitions with
generated failure-mode tests, ported from <private-repo>
``domain-kits/compiler/engine.py``.

The donor's YAML/pydantic layers are not ported; the store block accepts
the same sheet structure as JSON. Ported as-is: slugging, sheet
validation (domain required), table-to-lookup-block conversion, and
failure-mode test skeletons per generated block.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "domain_kit_compiler", "status": status, "result": result, "error": error, "detail": detail}


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    return cleaned.strip("_") or "unnamed"


def _load_sheet(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("domain sheet must be a mapping")
    if not str(data.get("domain", "")).strip():
        raise ValueError("domain sheet requires a non-empty 'domain' field")
    return data


def _block_from_table(domain: str, table: Dict[str, Any]) -> Dict[str, Any]:
    name = _slug(str(table.get("name", "")))
    block_id = f"{domain}_{name}_lookup"
    columns = table.get("columns") or []
    rows = table.get("rows") or []
    lookup_key = table.get("lookup_key") or (columns[0]["name"] if columns else "key")
    return {
        "block_id": block_id,
        "table": name,
        "lookup_key": lookup_key,
        "columns": [str(c["name"]) for c in columns if isinstance(c, dict) and "name" in c],
        "row_count": len(rows),
        "failure_mode_test": (
            f"test_{block_id}_missing_lookup_key: "
            f"an absent '{lookup_key}' must refuse, never return a fabricated row"
        ),
    }


class DomainKitCompilerBlock(UniversalBlock):
    """Compile a domain sheet into block definitions + failure-mode tests."""

    name = "domain_kit_compiler"
    version = "1.0.0"
    description = (
        "Domain kit compiler ported from <private-repo> domain-kits/compiler/engine.py: "
        "sheet validation (domain required), slugging, table-to-lookup-block "
        "conversion, and a failure-mode test per generated block."
    )
    layer = 3
    tags = ["domain-kit", "compiler", "<private-repo>"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "compile", "sheet": {"domain": "hr", "tables": [{"name": "grades", "columns": [{"name": "grade"}], "rows": []}]}}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "compile")).lower()
        try:
            if action == "compile":
                sheet = _load_sheet(payload.get("sheet") or {})
                domain = _slug(str(sheet["domain"]))
                tables = sheet.get("tables") or []
                blocks = [_block_from_table(domain, t) for t in tables if isinstance(t, dict) and t.get("name")]
                return _envelope("ok", {"domain": domain, "blocks": blocks, "count": len(blocks)})
            if action == "slug":
                return _envelope("ok", {"slug": _slug(str(payload.get("value", "")))})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["compile", "slug"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
