"""Ingestion Provenance — factory provenance payload + content hash tree,
ported from <private-repo> ``cerebrum_product_kernel/provenance.py``.

build_provenance and hash_tree are ported as-is; a ``record`` action adds
page/sheet/row provenance metadata for ingested documents so the donor's
page/sheet/row labelling survives extraction.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "ingestion_provenance", "status": status, "result": result, "error": error, "detail": detail}


def build_provenance(*, product_id, blueprint_id, factory_commit, blocks_commit, plan, inputs_hash) -> Dict[str, Any]:
    return {
        "blueprint_id": blueprint_id,
        "blocks_commit": blocks_commit,
        "factory": "<private-repo>",
        "factory_commit": factory_commit,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "inputs_hash": inputs_hash,
        "kernel_version": "1.0.0",
        "plan": plan,
        "product_id": product_id,
        "schema": "factory_provenance.v1",
    }


def hash_tree(root: str, ignore_names: set = None) -> str:
    ignore = ignore_names or {".git", "__pycache__", "provenance.json", ".pytest_cache"}
    h = hashlib.sha256()
    root_path = Path(root)
    if not root_path.is_dir():
        raise ValueError(f"not a directory: {root}")
    for path in sorted(root_path.rglob("*")):
        if not path.is_file():
            continue
        if any(part in ignore for part in path.parts):
            continue
        rel = path.relative_to(root_path).as_posix()
        h.update(rel.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


class IngestionProvenanceBlock(UniversalBlock):
    """Ingestion provenance ported from <private-repo>: factory provenance
    payloads, content hash trees, page/sheet/row source labelling."""

    name = "ingestion_provenance"
    version = "1.0.0"
    description = (
        "Ingestion provenance ported from <private-repo> cerebrum_product_kernel/"
        "provenance.py: factory provenance payloads, SHA-256 content hash trees, and "
        "page/sheet/row source labels for ingested documents."
    )
    layer = 3
    tags = ["provenance", "ingestion", "steward", "audit"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "record_source", "source": "boq.xlsx", "page": null, "sheet": "Sheet1", "row_start": 2, "row_end": 9}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._labels: List[Dict[str, Any]] = []

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "build")).lower()
        try:
            if action == "build":
                prov = build_provenance(
                    product_id=str(payload.get("product_id", "")),
                    blueprint_id=str(payload.get("blueprint_id", "")),
                    factory_commit=str(payload.get("factory_commit", "")),
                    blocks_commit=str(payload.get("blocks_commit", "")),
                    plan=payload.get("plan", {}),
                    inputs_hash=str(payload.get("inputs_hash", "")),
                )
                return _envelope("ok", {"provenance": prov})
            if action == "hash_tree":
                digest = hash_tree(str(payload.get("root", "")), ignore_names=set(payload.get("ignore", [])) or None)
                return _envelope("ok", {"digest": digest})
            if action in ("record_source", "record"):
                label = {
                    "source": str(payload.get("source", "")),
                    "page": payload.get("page"),
                    "sheet": payload.get("sheet"),
                    "row_start": payload.get("row_start"),
                    "row_end": payload.get("row_end"),
                    "recorded_at": time.time(),
                }
                if not label["source"]:
                    return _envelope("error", error="source is required")
                self._labels.append(label)
                return _envelope("ok", {"label": label})
            if action == "list_labels":
                return _envelope("ok", {"labels": list(self._labels)})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["build", "hash_tree", "record_source", "list_labels"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
