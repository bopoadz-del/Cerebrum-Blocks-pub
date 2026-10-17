"""Helpers for building UniversalBlock ui_schema manifests (JetForm-style self-description)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def _field(name: str, field_type: str, label: str) -> Dict[str, str]:
    return {"name": name, "type": field_type, "label": label}


def _param_from_value(name: str, value: Any) -> Dict[str, Any]:
    if isinstance(value, bool):
        return {"name": name, "type": "boolean", "label": name.replace("_", " ").title(), "default": value}
    if isinstance(value, int):
        return {"name": name, "type": "number", "label": name.replace("_", " ").title(), "default": value}
    if isinstance(value, float):
        return {"name": name, "type": "number", "label": name.replace("_", " ").title(), "default": value}
    if isinstance(value, (dict, list)):
        return {"name": name, "type": "json", "label": name.replace("_", " ").title(), "default": value}
    return {"name": name, "type": "text", "label": name.replace("_", " ").title(), "default": value}


def action_ui_schema(
    actions: Sequence[str],
    *,
    input_type: str = "json",
    placeholder: str = "JSON payload for the selected action",
    output_fields: Optional[List[Dict[str, str]]] = None,
    config_params: Optional[Dict[str, Any]] = None,
    quick_actions: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Standard schema for action-dispatch blocks (memory, auth, queue, etc.)."""
    params: List[Dict[str, Any]] = [
        {
            "name": "action",
            "type": "select",
            "label": "Action",
            "options": list(actions),
            "default": actions[0] if actions else "",
        }
    ]
    if config_params:
        for key, value in config_params.items():
            params.append(_param_from_value(key, value))

    return {
        "input": {
            "type": input_type,
            "accept": None,
            "placeholder": placeholder,
            "multiline": input_type in {"json", "text"},
        },
        "output": {
            "type": "json",
            "fields": output_fields
            or [{"name": "result", "type": "json", "label": "Result"}],
        },
        "params": params,
        "quick_actions": quick_actions or [],
    }


def text_ui_schema(
    *,
    placeholder: str = "Enter text...",
    output_name: str = "text",
    output_type: str = "text",
    config_params: Optional[Dict[str, Any]] = None,
    quick_actions: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    params = [_param_from_value(k, v) for k, v in (config_params or {}).items()]
    return {
        "input": {
            "type": "text",
            "accept": None,
            "placeholder": placeholder,
            "multiline": True,
        },
        "output": {
            "type": output_type,
            "fields": [{"name": output_name, "type": output_type, "label": output_name.replace("_", " ").title()}],
        },
        "params": params,
        "quick_actions": quick_actions or [],
    }


def file_ui_schema(
    *,
    accept: Sequence[str],
    placeholder: str = "Upload file...",
    output_fields: Optional[List[Dict[str, str]]] = None,
    config_params: Optional[Dict[str, Any]] = None,
    quick_actions: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    params = [_param_from_value(k, v) for k, v in (config_params or {}).items()]
    return {
        "input": {
            "type": "file",
            "accept": list(accept),
            "placeholder": placeholder,
            "multiline": False,
        },
        "output": {
            "type": "json",
            "fields": output_fields
            or [{"name": "result", "type": "json", "label": "Result"}],
        },
        "params": params,
        "quick_actions": quick_actions or [],
    }


def payload_ui_schema(
    *,
    input_fields: Sequence[Dict[str, str]],
    config_params: Optional[Dict[str, Any]] = None,
    output_fields: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Schema for blocks that accept structured payloads (failover, orchestrator helpers)."""
    params = [_param_from_value(k, v) for k, v in (config_params or {}).items()]
    return {
        "input": {
            "type": "json",
            "accept": None,
            "placeholder": "Structured input payload",
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": output_fields
            or [{"name": "result", "type": "json", "label": "Result"}],
        },
        "params": params,
        "input_fields": list(input_fields),
        "quick_actions": [],
    }
