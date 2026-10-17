"""Agent State Sync — vector-clock deltas with conflict archiving, ported
from <private-repo> ``agent/memory.py`` (MemoryDelta / SyncConflict schema).

SQLite is not ported. The store block ports the sync SEMANTICS: deltas
carry (key, origin, vector_clock, operation); a delta applies when its
clock dominates the stored one; incomparable clocks on the same key are
archived as conflicts, never silently dropped.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "agent_state_sync", "status": status, "result": result, "error": error, "detail": detail}


def _dominates(a: Dict[str, int], b: Dict[str, int]) -> bool:
    """a dominates b iff a >= b on every origin and > on at least one."""
    origins = set(a) | set(b)
    strictly = False
    for o in origins:
        if a.get(o, 0) < b.get(o, 0):
            return False
        if a.get(o, 0) > b.get(o, 0):
            strictly = True
    return strictly


class AgentStateSyncBlock(UniversalBlock):
    """Vector-clock state sync with conflict archive."""

    name = "agent_state_sync"
    version = "1.0.0"
    description = (
        "Agent state sync ported from <private-repo> agent/memory.py: deltas carry "
        "(key, origin, vector_clock, operation); a delta applies when its clock "
        "dominates the stored one; incomparable clocks on the same key are "
        "archived as conflicts, never silently dropped. Store is in-process."
    )
    layer = 3
    tags = ["agent", "state-sync", "vector-clock", "<private-repo>"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "apply", "deltas": [{"key": "k", "value": "v", "origin": "a1", "vector_clock": {"a1": 1}, "operation": "put"}]}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._state: Dict[str, Dict[str, Any]] = {}
        self._conflicts: List[Dict[str, Any]] = []

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "apply")).lower()
        try:
            if action == "apply":
                return self._apply(payload.get("deltas") or [])
            if action == "get":
                key = str(payload.get("key", ""))
                return _envelope("ok", {"value": self._state.get(key)})
            if action == "conflicts":
                return _envelope("ok", {"conflicts": list(self._conflicts), "count": len(self._conflicts)})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["apply", "get", "conflicts"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    def _apply(self, deltas: List[Dict[str, Any]]) -> Dict[str, Any]:
        applied, conflicted = 0, 0
        for delta in deltas:
            key = str(delta.get("key", ""))
            clock = {str(k): int(v) for k, v in (delta.get("vector_clock") or {}).items()}
            if not key or not clock:
                return _envelope("error", error="each delta requires key and vector_clock")
            current = self._state.get(key)
            if current is None:
                self._state[key] = {"key": key, "value": delta.get("value"), "origin": delta.get("origin"), "vector_clock": clock, "operation": delta.get("operation", "put"), "timestamp": time.time()}
                applied += 1
                continue
            if _dominates(clock, current["vector_clock"]):
                self._state[key] = {"key": key, "value": delta.get("value"), "origin": delta.get("origin"), "vector_clock": clock, "operation": delta.get("operation", "put"), "timestamp": time.time()}
                applied += 1
            elif _dominates(current["vector_clock"], clock):
                continue  # stale write, dropped deterministically
            else:
                # Incomparable clocks: archive, never silently drop.
                self._conflicts.append({
                    "key": key,
                    "incoming": {"origin": delta.get("origin"), "vector_clock": clock, "value": delta.get("value")},
                    "stored": {"origin": current.get("origin"), "vector_clock": current.get("vector_clock"), "value": current.get("value")},
                    "archived_at": time.time(),
                })
                conflicted += 1
        return _envelope("ok", {"applied": applied, "conflicted": conflicted})
