"""Verified Outcome Learning — verified-only learning events with
per-module payload validation, ported from <client>
``retailops/learning/engine.py``.

SQLAlchemy is not ported. Ported exactly: a module registry with strict
payload validation, record_verified_outcome semantics — only
``verification_status == "verified"`` events may update learning
profiles; unverified events are stored but never applied — and
deterministic deduplication keys. In-process store.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "verified_outcome_learning", "status": status, "result": result, "error": error, "detail": detail}


def _id(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return "rl_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


_MODULES = {
    "demand_reorder": {"required": ["sku", "lead_time_days"]},
    "supplier_fulfilment": {"required": ["supplier_id", "order_id"]},
    "promotion_effectiveness": {"required": ["promotion_id"]},
    "store_exception": {"required": ["store_id", "exception_type"]},
}


class VerifiedOutcomeLearningBlock(UniversalBlock):
    """Verified-only outcome learning engine."""

    name = "verified_outcome_learning"
    version = "1.0.0"
    description = (
        "Verified outcome learning ported from <client> retailops/learning/"
        "engine.py: per-module payload validation, verified-only profile updates "
        "(unverified events are stored but never applied), deterministic "
        "deduplication keys, tenant scoping. Store is in-process."
    )
    layer = 3
    tags = ["learning", "verified-outcome", "retail", "<client>"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "record", "tenant_id": "t1", "project_id": "p1", "module": "demand_reorder", "payload": {"sku": "s1", "lead_time_days": 3}, "verified_by": "u1", "deduplication_key": "k1", "verification_status": "verified"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._events: Dict[str, Dict[str, Any]] = {}
        self._profiles: Dict[str, Dict[str, Any]] = {}
        self._applied: List[str] = []

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "record")).lower()
        try:
            if action == "validate":
                module = str(payload.get("module", ""))
                if module not in _MODULES:
                    return _envelope("error", error=f"unknown_module:{module}")
                missing = [f for f in _MODULES[module]["required"] if not (payload.get("payload") or {}).get(f)]
                return _envelope("ok", {"valid": not missing, "missing": missing})
            if action == "record":
                return self._record(payload)
            if action == "profile":
                return _envelope("ok", {"profile": self._profiles.get(str(payload.get("tenant_id", "")), {})})
            if action == "modules":
                return _envelope("ok", {"modules": sorted(_MODULES)})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["validate", "record", "profile", "modules"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    def _record(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tenant_id = str(payload.get("tenant_id", ""))
        project_id = str(payload.get("project_id", ""))
        if not tenant_id or not project_id:
            return _envelope("error", error="tenant_id and project_id are mandatory")
        module = str(payload.get("module", ""))
        if module not in _MODULES:
            return _envelope("error", error=f"unknown_module:{module}")
        missing = [f for f in _MODULES[module]["required"] if not (payload.get("payload") or {}).get(f)]
        if missing:
            return _envelope("refused", error=f"payload missing required fields: {', '.join(missing)}")
        status = str(payload.get("verification_status", "verified"))
        event = {
            "id": _id(tenant_id, project_id, module, payload.get("deduplication_key", "")),
            "tenant_id": tenant_id,
            "project_id": project_id,
            "module": module,
            "payload": payload.get("payload") or {},
            "verified_by": str(payload.get("verified_by", "")),
            "deduplication_key": str(payload.get("deduplication_key", "")),
            "verification_status": status,
        }
        self._events[event["id"]] = event
        if status == "verified":
            # Verified only: profiles update.
            profile = self._profiles.setdefault(tenant_id, {"module_events": {}, "last_event_id": None})
            profile["module_events"].setdefault(module, []).append(event["id"])
            profile["last_event_id"] = event["id"]
            self._applied.append(event["id"])
            return _envelope("ok", {"event": event, "applied": True})
        # Unverified events are stored but must not update profiles.
        return _envelope("ok", {"event": event, "applied": False})
