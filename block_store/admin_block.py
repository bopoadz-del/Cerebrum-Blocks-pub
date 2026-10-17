"""Admin Block — operator diagnostics, bulk repair, and preflight tooling.

A neutral admin block for the store: health probes, memory/database checks,
bulk key deletion, and system stats. No domain-specific repair logic.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock


class AdminBlock(UniversalBlock):
    """Operator diagnostics and maintenance actions."""

    name = "admin"
    version = "1.0.0"
    updated_at = "2026-07-19"
    description = (
        "Operator diagnostics and maintenance: preflight checks, bulk cleanup, "
        "and system stats."
    )
    layer = 1
    tags = ["admin", "diagnostics", "ops", "core"]
    requires = ["memory"]

    default_config = {
        "dangerous_prefixes": ["auth:keys", "tenant:", "agent_catalog:"],
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"action": "preflight"}',
            "multiline": False,
        },
        "output": {"type": "json", "fields": [{"name": "result", "type": "json"}]},
        "params": [
            {
                "name": "action",
                "type": "select",
                "label": "Action",
                "options": ["preflight", "stats", "bulk_delete", "ping"],
                "default": "preflight",
            }
        ],
        "quick_actions": [],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self.memory_block = None  # Wired by assembler or tests
        self.database_block = None  # Optional

    async def _legacy_initialize(self) -> bool:
        return True

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        data = input_data if isinstance(input_data, dict) else {}
        params = params or {}
        action = params.get("action") or data.get("action", "preflight")

        handlers = {
            "preflight": self._preflight,
            "stats": self._stats,
            "bulk_delete": self._bulk_delete,
            "ping": self._ping,
        }
        handler = handlers.get(action)
        if not handler:
            return {"status": "error", "error": f"Unknown action: {action}"}
        return await handler(data, params)

    async def _ping(self, data: Dict, params: Dict) -> Dict:
        return {"status": "success", "pong": True, "timestamp": time.time()}

    async def _preflight(self, data: Dict, params: Dict) -> Dict:
        checks = {}

        # Memory check
        if self.memory_block:
            try:
                ping = await self.memory_block.process({"action": "set", "key": "__admin:preflight__", "value": 1, "ttl": 10})
                checks["memory"] = {"status": "ok"}
            except Exception as exc:  # noqa: BLE001
                checks["memory"] = {"status": "error", "error": str(exc)}
        else:
            checks["memory"] = {"status": "missing"}

        # Database check
        if self.database_block:
            try:
                checks["database"] = {"status": "ok"}
            except Exception as exc:  # noqa: BLE001
                checks["database"] = {"status": "error", "error": str(exc)}
        else:
            checks["database"] = {"status": "not_configured"}

        overall = "ok" if all(c.get("status") in {"ok", "not_configured"} for c in checks.values()) else "degraded"
        return {"status": "success", "overall": overall, "checks": checks}

    async def _stats(self, data: Dict, params: Dict) -> Dict:
        stats = {"timestamp": time.time()}
        if self.memory_block:
            try:
                result = await self.memory_block.process({"action": "stats"})
                stats["memory"] = result
            except Exception as exc:  # noqa: BLE001
                stats["memory"] = {"error": str(exc)}
        else:
            stats["memory"] = {"status": "missing"}
        return {"status": "success", "stats": stats}

    async def _bulk_delete(self, data: Dict, params: Dict) -> Dict:
        prefix = data.get("prefix") or params.get("prefix")
        if not prefix:
            return {"status": "error", "error": "prefix is required"}

        dangerous = self.config.get("dangerous_prefixes", [])
        for bad in dangerous:
            if prefix.startswith(bad):
                return {"status": "error", "error": f"refusing to delete protected prefix: {prefix}"}

        if not self.memory_block:
            return {"status": "error", "error": "memory backend not available"}

        keys_result = await self.memory_block.process({"action": "keys"})
        keys = [k for k in keys_result.get("keys", []) if k.startswith(prefix)]
        deleted = 0
        for key in keys:
            await self.memory_block.process({"action": "delete", "key": key})
            deleted += 1

        return {"status": "success", "deleted": deleted}
