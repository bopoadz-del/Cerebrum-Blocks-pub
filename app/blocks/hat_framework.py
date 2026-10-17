"""Hat Framework — base agents + discipline hats with composition, ported
from <client> ``retailops/agents/catalog.py`` + ``models.py``.

Ported: the manifest contract (kind base|hat, policies, formulas) and
the catalog (register/get/bases/hats/compose). ``compose`` overlays a
hat onto its base agent and refuses when the hat is unknown or the base
is missing. In-process catalog.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "hat_framework", "status": status, "result": result, "error": error, "detail": detail}


_MANIFEST_FIELDS = {"id", "name", "kind", "base_agent_id"}


def _validate_manifest(m: Dict[str, Any]) -> Optional[str]:
    if m.get("kind") not in ("base", "hat"):
        return "kind must be 'base' or 'hat'"
    if not str(m.get("id", "")).strip():
        return "id is required"
    if m.get("kind") == "hat" and not str(m.get("base_agent_id", "")).strip():
        return "hat manifests require base_agent_id"
    return None


class HatFrameworkBlock(UniversalBlock):
    """Base-agent + discipline-hat catalog with composition."""

    name = "hat_framework"
    version = "1.0.0"
    description = (
        "Hat framework ported from <client> retailops/agents/catalog.py: a "
        "manifest contract (kind base|hat, policies, formulas) and a catalog with "
        "register/get/bases/hats/compose. Compose overlays a hat onto its base "
        "agent and refuses on a missing base or unknown hat. In-process catalog."
    )
    layer = 3
    tags = ["agent", "hat", "composition", "<client>"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "register", "manifest": {"id": "planner", "kind": "base", "name": "Planner"}}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._manifests: Dict[str, Dict[str, Any]] = {}

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "register")).lower()
        try:
            if action == "register":
                manifest = payload.get("manifest") or {}
                problem = _validate_manifest(manifest)
                if problem:
                    return _envelope("refused", error=problem)
                self._manifests[str(manifest["id"])] = dict(manifest)
                return _envelope("ok", {"manifest": self._manifests[str(manifest["id"])]})
            if action == "get":
                mid = str(payload.get("id", ""))
                rec = self._manifests.get(mid)
                if rec is None:
                    return _envelope("error", error="manifest not found")
                return _envelope("ok", {"manifest": rec})
            if action == "bases":
                return _envelope("ok", {"manifests": [m for m in self._manifests.values() if m["kind"] == "base"]})
            if action == "hats":
                return _envelope("ok", {"manifests": [m for m in self._manifests.values() if m["kind"] == "hat"]})
            if action == "compose":
                return self._compose(payload)
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["register", "get", "bases", "hats", "compose"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    def _compose(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        hat_id = str(payload.get("hat_id", ""))
        hat = self._manifests.get(hat_id)
        if hat is None or hat["kind"] != "hat":
            return _envelope("refused", error="hat not found or not a hat")
        base = self._manifests.get(str(hat.get("base_agent_id", "")))
        if base is None or base["kind"] != "base":
            return _envelope("refused", error="base agent not found or not a base")
        composed = dict(base)
        composed["id"] = f"{base['id']}+{hat_id}"
        composed["hat"] = hat_id
        composed["policies"] = (base.get("policies") or []) + (hat.get("policies") or [])
        composed["formulas"] = (base.get("formulas") or []) + (hat.get("formulas") or [])
        return _envelope("ok", {"composed": composed})
