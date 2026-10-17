"""Mock Connector Bus — fail-closed connector taxonomy with a normalised
event bus, ported from <private-repo>-v2 ``connectors/base.py`` +
``event_bus.py``.

Ported exactly: MockLevel LIVE/MOCK_UNAVAILABLE, fetch() failing closed
with a structured refusal that NEVER fabricates operational data, and the
canonical CRM normalisation + event-bus publish with per-system topics.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "mock_connector_bus", "status": status, "result": result, "error": error, "detail": detail}


class MockLevel(str, Enum):
    LIVE = "live"
    MOCK_UNAVAILABLE = "mock_unavailable"


CONNECTOR_SYSTEMS = {
    "opera": ("opera", ("guest", "reservation")),
    "micros": ("micros", ("pos", "transaction")),
    "grms": ("grms", ("maintenance", "asset")),
    "gaming_cms": ("gaming_cms", ("player", "session")),
    "loyalty_lms": ("loyalty_lms", ("member", "redemption")),
    "maximo": ("maximo", ("workorder", "inventory")),
}


class MockConnectorBusBlock(UniversalBlock):
    """Fail-closed mock connector taxonomy + normalised event bus."""

    name = "mock_connector_bus"
    version = "1.0.0"
    description = (
        "Fail-closed connector taxonomy ported from <private-repo>-v2 "
        "connectors/base.py + event_bus.py: six enterprise systems (opera, micros, "
        "grms, gaming_cms, loyalty_lms, maximo) in mock_unavailable level — fetch "
        "fails closed with a structured refusal and NEVER fabricates operational "
        "data; events normalise onto a canonical CRM taxonomy and publish per "
        "system topic. In-process bus."
    )
    layer = 3
    tags = ["connector", "hotel", "mock", "fail-closed", "hotelops-v2"]
    requires = []

    default_config = {"systems": {k: v[0] for k, v in CONNECTOR_SYSTEMS.items()}}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "fetch", "system": "opera"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._topics: Dict[str, List[Dict[str, Any]]] = {}

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "fetch")).lower()
        try:
            if action == "fetch":
                system = str(payload.get("system", "")).lower()
                if system not in CONNECTOR_SYSTEMS:
                    return _envelope("error", error=f"unknown system: {system}", detail={"known": sorted(CONNECTOR_SYSTEMS)})
                return _envelope("ok", {
                    "system": CONNECTOR_SYSTEMS[system][0],
                    "available": False,
                    "mock_level": MockLevel.MOCK_UNAVAILABLE.value,
                    "data": [],
                    "refusal": f"{CONNECTOR_SYSTEMS[system][0]} has no live integration in this deployment. No operational data is fabricated.",
                })
            if action == "normalise":
                system = str(payload.get("system", "")).lower()
                if system not in CONNECTOR_SYSTEMS:
                    return _envelope("error", error=f"unknown system: {system}")
                return _envelope("ok", {"system": CONNECTOR_SYSTEMS[system][0], "event": dict(payload.get("event") or {})})
            if action == "publish":
                system = str(payload.get("system", "")).lower()
                if system not in CONNECTOR_SYSTEMS:
                    return _envelope("error", error=f"unknown system: {system}")
                self._topics.setdefault(system, []).append(dict(payload.get("event") or {}))
                return _envelope("ok", {"published_to": system, "count": len(self._topics[system])})
            if action == "topics":
                return _envelope("ok", {"topics": {k: len(v) for k, v in self._topics.items()}})
            if action == "systems":
                return _envelope("ok", {"systems": [{"system": v[0], "event_topics": list(v[1]), "mock_level": "mock_unavailable"} for v in CONNECTOR_SYSTEMS.values()]})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["fetch", "normalise", "publish", "topics", "systems"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
