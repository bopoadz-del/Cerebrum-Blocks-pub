"""Zone Arbitration — cross-zone proposal arbitration with the double-pass
contract, ported from <private-repo> ``app/agents/coordinator.py``
(``arbitrate``).

The monitor machinery is the product's; this block enforces the contract:
a proposal whose element is shared between zones commits ONLY when every
owning zone's monitor passes. A single pass — one zone happy, the other
never asked — is refused, because that is exactly the failure zoning
introduced and this step exists to close. In-process.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "zone_arbitration", "status": status, "result": result, "error": error, "detail": detail}


class ZoneArbitrationBlock(UniversalBlock):
    """Cross-zone double-pass arbitration ported from <private-repo>."""

    name = "zone_arbitration"
    version = "1.0.0"
    description = (
        "Zone arbitration ported from <private-repo> agents/coordinator.py "
        "arbitrate(): a shared clash's proposal commits only when every owning "
        "zone's monitor passes (double pass). A single pass is refused — one "
        "zone happy and the other unasked is the failure zoning introduced. "
        "The monitors themselves are the product's; this block enforces the "
        "double-pass contract. In-process."
    )
    layer = 3
    tags = ["bim", "coordination", "arbitration", "multi-zone", "bim-manager"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "arbitrate", "clash_id": "c1", "zones": [{"zone_key": "z1", "verdict": "pass"}, {"zone_key": "z2", "verdict": "pass"}], "has_proposal": true}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._committed: List[Dict[str, Any]] = []

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "arbitrate")).lower()
        try:
            if action == "arbitrate":
                return self._arbitrate(payload)
            if action == "committed":
                return _envelope("ok", {"committed": list(self._committed), "count": len(self._committed)})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["arbitrate", "committed"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    def _arbitrate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        clash_id = str(payload.get("clash_id", ""))
        if not clash_id:
            return _envelope("error", error="clash_id is required")
        if not payload.get("has_proposal", False):
            return _envelope("refused", error="no proposal to arbitrate", detail={"clash_id": clash_id})
        zones = payload.get("zones") or []
        if len(zones) < 2:
            return _envelope("refused", error="clash is not actually shared between two zones", detail={"zones_checked": [z.get("zone_key") for z in zones]})
        verdicts = {str(z.get("zone_key")): str(z.get("verdict", "unasked")).lower() for z in zones}
        if "unasked" in verdicts.values():
            unasked = [k for k, v in verdicts.items() if v == "unasked"]
            return _envelope("refused", error="one zone has not been asked", detail={"zones_unasked": unasked})
        failing = [k for k, v in verdicts.items() if v != "pass"]
        if failing:
            return _envelope("refused", error="single pass refused — at least one zone monitor failed", detail={"zones_failed": failing, "zones_checked": sorted(verdicts)})
        record = {"clash_id": clash_id, "zones_checked": sorted(verdicts), "committed_at": time.time()}
        self._committed.append(record)
        return _envelope("ok", {"committed": True, "arbitration": record})
