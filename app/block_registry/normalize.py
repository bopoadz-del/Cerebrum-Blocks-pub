"""Normalize registry manifests and API-facing block metadata."""

from __future__ import annotations

from typing import Any, Dict, List


def manifest_widgets_to_universal_ui(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Convert block.json widget list to UniversalBlock ui_schema shape."""
    widgets = manifest.get("ui_schema", [])
    if isinstance(widgets, dict):
        # Legacy object form — pass through for callers that still handle it.
        return widgets

    primary = next((w for w in widgets if w.get("name") == "input"), widgets[0] if widgets else None)
    ui_input = primary or {}
    widget_type = ui_input.get("widget", "text")
    input_type = {
        "text": "text",
        "textarea": "text",
        "file": "file",
        "number": "number",
        "toggle": "boolean",
        "json": "json",
        "select": "text",
    }.get(widget_type, "text")

    output_fields = []
    for output in manifest.get("outputs", []):
        if not isinstance(output, dict):
            continue
        output_fields.append(
            {
                "name": output.get("name", "result"),
                "type": output.get("type", "json"),
                "label": output.get("description") or output.get("name", "result"),
            }
        )

    return {
        "input": {
            "type": input_type,
            "accept": ui_input.get("accept"),
            "placeholder": (primary or {}).get("label", ui_input.get("placeholder", "Enter input...")),
            "multiline": widget_type in {"textarea", "json"} or ui_input.get("multiline", False),
        },
        "output": {
            "type": "json" if len(output_fields) != 1 else output_fields[0].get("type", "json"),
            "fields": output_fields or [{"name": "result", "type": "json"}],
        },
        "quick_actions": manifest.get("quick_actions", []),
        "params": [
            {
                "name": widget.get("name"),
                "type": {
                    "toggle": "boolean",
                    "number": "number",
                    "json": "json",
                    "select": "select",
                    "file": "file",
                    "textarea": "text",
                }.get(widget.get("widget", "text"), "text"),
                "label": widget.get("label", widget.get("name", "")),
                **({"options": widget["options"]} if widget.get("options") else {}),
            }
            for widget in widgets
            if isinstance(widget, dict) and widget.get("name") and widget.get("name") != "input"
        ],
    }


def registry_block_response(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Format a registry manifest like GET /blocks items."""
    return {
        "name": manifest["id"],
        "version": manifest.get("version", "1.0"),
        "description": manifest.get("description", ""),
        "layer": manifest.get("layer", 3),
        "tags": manifest.get("tags", []),
        "requires": manifest.get("requires", []),
        "ui_schema": manifest_widgets_to_universal_ui(manifest),
        "source": "registry",
        "manifest": manifest,
    }
