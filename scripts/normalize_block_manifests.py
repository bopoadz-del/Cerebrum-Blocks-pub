#!/usr/bin/env python3
"""
Patch block_registry manifests to the plug-and-play standard without importing app.blocks.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
REGISTRY_ROOT = ROOT / "block_registry"
APP_BLOCKS_ROOT = ROOT / "app" / "blocks"
SKIP_DIRS = {"__pycache__"}


def _parse_block_metadata(block_name: str) -> dict:
    module_path = APP_BLOCKS_ROOT / f"{block_name}.py"
    if not module_path.exists():
        return {}

    source = module_path.read_text(encoding="utf-8", errors="replace")
    metadata = {}

    for field in ("layer", "version"):
        match = re.search(rf"^\s*{field}\s*=\s*([^\n#]+)", source, re.MULTILINE)
        if match:
            value = match.group(1).strip().strip('"').strip("'")
            metadata[field] = int(value) if field == "layer" and value.isdigit() else value

    for field in ("description", "author"):
        match = re.search(rf'^\s*{field}\s*=\s*"([^"]*)"', source, re.MULTILINE)
        if match:
            metadata[field] = match.group(1)

    requires_match = re.search(r"^\s*requires\s*=\s*\[(.*?)\]", source, re.MULTILINE | re.DOTALL)
    if requires_match:
        metadata["requires"] = re.findall(r'"([^"]+)"', requires_match.group(1))

    tags_match = re.search(r"^\s*tags\s*=\s*\[(.*?)\]", source, re.MULTILINE | re.DOTALL)
    if tags_match:
        metadata["tags"] = re.findall(r'"([^"]+)"', tags_match.group(1))

    return metadata


def _legacy_ui_to_widgets(ui_schema: dict) -> list:
    widgets = []
    for key, value in ui_schema.items():
        if not isinstance(value, dict):
            continue
        widget_type = value.get("type", "text")
        widget = {
            "select": "select",
            "textarea": "textarea",
            "boolean": "toggle",
            "number": "number",
            "json": "json",
            "file": "file",
        }.get(widget_type, "text")
        widgets.append(
            {
                "name": key,
                "widget": widget,
                "label": value.get("label", key.replace("_", " ").title()),
            }
        )
    return widgets


def normalize_manifest(block_name: str, manifest: dict) -> dict:
    meta = _parse_block_metadata(block_name)

    manifest.setdefault("id", block_name)
    manifest.setdefault("name", block_name.replace("_", " ").title())
    manifest.setdefault("version", meta.get("version", "1.0.0"))
    manifest.setdefault("author", meta.get("author") or "Cerebrum Team")
    manifest.setdefault("description", meta.get("description", f"{block_name} block"))
    manifest.setdefault("layer", meta.get("layer", 3))
    manifest.setdefault("requires", meta.get("requires", []))
    manifest.setdefault("tags", meta.get("tags", []))
    manifest.setdefault("trust_tier", "platform")

    if isinstance(manifest.get("ui_schema"), dict):
        manifest["ui_schema"] = _legacy_ui_to_widgets(manifest["ui_schema"])

    if not manifest.get("inputs"):
        manifest["inputs"] = [
            {
                "name": "input",
                "type": "json",
                "required": False,
                "description": manifest.get("description", "Block input"),
            }
        ]

    if not manifest.get("outputs"):
        manifest["outputs"] = [{"name": "result", "type": "json", "description": "Block result"}]

    if not manifest.get("execution"):
        manifest["execution"] = {
            "type": "docker",
            "image": f"ghcr.io/cerebrum-blocks/{block_name}:latest",
        }

    if manifest["execution"].get("type") == "python":
        manifest["execution"] = {
            "type": "docker",
            "image": f"ghcr.io/cerebrum-blocks/{block_name}:latest",
        }

    return manifest


def main() -> int:
    updated = 0
    for block_dir in sorted(REGISTRY_ROOT.iterdir()):
        if not block_dir.is_dir() or block_dir.name in SKIP_DIRS:
            continue

        manifest_path = block_dir / "block.json"
        if not manifest_path.exists():
            continue

        original = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(original)
        normalized = normalize_manifest(block_dir.name, manifest)
        new_text = json.dumps(normalized, indent=2) + "\n"
        if new_text != original:
            manifest_path.write_text(new_text, encoding="utf-8")
            updated += 1
            print(f"[OK] normalized {block_dir.name}/block.json")

    print(f"Updated {updated} manifests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
