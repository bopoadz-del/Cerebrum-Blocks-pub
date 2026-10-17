"""Cerebrum self-healing + hot-swap layer state machine.

Ported from C:\\Users\\<owner>\\Cerebrum\\backend\\app\\agent\\core_real.py:
- the 14-layer AgentLayer enum (CODING..MONITORING, incl. HOTSWAP and
  HEALING),
- the AgentAction enum (incl. HEAL_ERROR),
- the deterministic move_to_layer transition (previous -> current layer,
  action read_memory, donor AgentResult shape).

And from C:\\Users\\<owner>\\Cerebrum\\backend\\app\\healing\\patch_generation.py:
- SelfHealingEngine's deterministic gating: confidence threshold 0.8,
  auto-heal flag default OFF, healing history, and the handle_error
  decision flow (failed patch -> unhealed; confidence < threshold ->
  unhealed; heal + apply only when auto_apply and auto-heal are both on).

The LLM paths are deliberately NOT ported (core_real's heal_error tool is
a stub in the donor and patch_generation's PatchGenerator is an OpenAI
client). Without a caller-supplied deterministic patch, handle_error fails
closed with a structured refusal — this block never fabricates a healed
outcome.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "cerebrum_self_healing",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


# Ported from core_real.py AgentLayer (14 layers).
LAYERS = [
    "coding",
    "registry",
    "validation",
    "hotswap",
    "healing",
    "prompts",
    "triggers",
    "economics",
    "vdc",
    "edge",
    "portal",
    "enterprise",
    "connectors",
    "monitoring",
]

# Ported from core_real.py AgentAction.
ACTIONS = [
    "generate_code",
    "validate_code",
    "deploy_code",
    "read_conversation",
    "read_memory",
    "write_memory",
    "heal_error",
    "query_bim",
    "calculate_cost",
    "execute_sandbox",
]


class CerebrumSelfHealingBlock(UniversalBlock):
    """Deterministic layer/state machine + healing gating (LLM paths not ported)."""

    name = "cerebrum_self_healing"
    version = "1.0.0"
    description = (
        "real — Cerebrum self-healing + hot-swap state machine ported from "
        "C:\\Users\\<owner>\\Cerebrum\\backend\\app\\agent\\core_real.py (AgentLayer "
        "HOTSWAP/HEALING, AgentAction HEAL_ERROR, move_to_layer) and "
        "backend/app/healing/patch_generation.py (SelfHealingEngine confidence "
        "gating, auto-heal flag, healing history). LLM calls are not ported: "
        "handle_error without a caller-supplied deterministic patch fails closed "
        "with a structured refusal."
    )
    layer = 2
    tags = ["cerebrum", "self-healing", "hotswap", "state-machine", "agent-core"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"action": "move_layer", "to": "healing"}',
            "multiline": True,
        },
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}]},
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self.current_layer = "coding"
        self._auto_heal_enabled = False
        self._confidence_threshold = 0.8
        self._healing_history: List[Dict[str, Any]] = []

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "status")).lower()
        try:
            if action == "layers":
                return _envelope("ok", {"layers": list(LAYERS)})
            if action == "actions":
                return _envelope("ok", {"actions": list(ACTIONS)})
            if action == "move_layer":
                return self._move_layer(payload)
            if action == "handle_error":
                return self._handle_error(payload)
            if action == "heal_error":
                # Donor _tool_heal_error (core_real.py) is a stub returning a
                # fabricated {"success": True, "incidents": 0}. Not ported as a
                # success — the analysis tool does not exist.
                return _envelope(
                    "refused",
                    error=(
                        "heal_error analysis is a stub in the donor "
                        "(core_real.py _tool_heal_error); no incidents are "
                        "computed here. Use handle_error with a deterministic patch."
                    ),
                    detail={"action": "heal_error", "ported": False},
                )
            if action == "set_confidence_threshold":
                return self._set_confidence_threshold(payload)
            if action == "enable_auto_heal":
                return self._enable_auto_heal(payload)
            if action == "healing_history":
                return _envelope("ok", {"history": list(self._healing_history)})
            if action == "status":
                return _envelope("ok", {
                    "current_layer": self.current_layer,
                    "auto_heal_enabled": self._auto_heal_enabled,
                    "confidence_threshold": self._confidence_threshold,
                    "history_len": len(self._healing_history),
                })
            return _envelope(
                "error",
                error=f"unknown action: {action}",
                detail={"known": [
                    "layers", "actions", "move_layer", "handle_error",
                    "heal_error", "set_confidence_threshold",
                    "enable_auto_heal", "healing_history", "status",
                ]},
            )
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    def _move_layer(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        target = str(payload.get("to", payload.get("layer", ""))).lower()
        if target not in LAYERS:
            return _envelope(
                "refused",
                error=f"unknown layer: {target}",
                detail={"known_layers": list(LAYERS)},
            )
        old_layer = self.current_layer
        self.current_layer = target
        # Ported from core_real.py move_to_layer AgentResult shape.
        return _envelope("ok", {
            "success": True,
            "action": "read_memory",
            "layer": target,
            "data": {"previous_layer": old_layer, "current_layer": target},
            "message": f"Moved from {old_layer} to {target}",
        })

    def _handle_error(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        event = payload.get("error_event") or {}
        if not isinstance(event, dict):
            return _envelope("error", error="error_event must be a dict")
        error_id = str(event.get("event_id", event.get("error_id", "")))
        auto_apply = bool(payload.get("auto_apply", False))
        patch = payload.get("patch")
        if patch is None:
            # SelfHealingEngine.handle_error would call the OpenAI
            # PatchGenerator here. LLM calls are not ported: fail closed.
            return _envelope(
                "refused",
                error=(
                    "patch generation unavailable — the donor's LLM "
                    "PatchGenerator (patch_generation.py) is not ported into "
                    "this block; supply a deterministic patch dict or leave "
                    "the error unhealed"
                ),
                detail={"error_id": error_id, "healed": False},
            )
        if not isinstance(patch, dict) or "success" not in patch:
            return _envelope(
                "error",
                error="patch must be a dict with a 'success' flag (PatchResult shape)",
                detail={"error_id": error_id},
            )
        # Ported from SelfHealingEngine.handle_error decision flow.
        if not patch.get("success"):
            return _envelope("ok", {
                "error_id": error_id,
                "healed": False,
                "applied": False,
                "message": "Failed to generate patch",
                "patch": patch,
            })
        confidence = float(patch.get("confidence", 0.0))
        if confidence < self._confidence_threshold:
            return _envelope("ok", {
                "error_id": error_id,
                "healed": False,
                "applied": False,
                "message": (
                    f"Patch confidence {confidence} below threshold "
                    f"{self._confidence_threshold}"
                ),
                "patch": patch,
            })
        applied = auto_apply and self._auto_heal_enabled
        message = "Patch auto-applied" if applied else "Patch generated, awaiting approval"
        self._healing_history.append({
            "error_id": error_id,
            "patch_id": patch.get("patch_id"),
            "applied": applied,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return _envelope("ok", {
            "error_id": error_id,
            "healed": True,
            "applied": applied,
            "message": message,
            "patch": patch,
        })

    def _set_confidence_threshold(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            threshold = float(payload.get("threshold", self._confidence_threshold))
        except (TypeError, ValueError):
            return _envelope("error", error="threshold must be a number")
        # Ported from patch_generation.py set_confidence_threshold clamp.
        self._confidence_threshold = max(0.0, min(1.0, threshold))
        return _envelope("ok", {"confidence_threshold": self._confidence_threshold})

    def _enable_auto_heal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._auto_heal_enabled = bool(payload.get("enabled", True))
        return _envelope("ok", {"auto_heal_enabled": self._auto_heal_enabled})
