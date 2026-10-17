"""Hotel Management Suite — domain container stub."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict

from app.containers.base import DomainContainer


class HotelManagementContainer(DomainContainer):
    name = "hotel_management"
    description = "Guest services, reservations, housekeeping, and hospitality operations blocks."
    version = "0.0.0-skeleton"
    system_prompt_file = "hotel_management_expert.txt"

    def __init__(self, kit_root: Path | None = None) -> None:
        self.kit_root = kit_root or Path(__file__).resolve().parent

    def get_actions(self) -> Dict[str, Callable]:
        return {
            "opera_fetch": self._opera_fetch,
            "hotel_trigger": self._hotel_trigger,
            "health": self._health,
        }

    async def _health(self, input_data: Any, params: Dict) -> Dict:
        return {"status": "healthy", "container": self.name, "version": self.version}

    async def _opera_fetch(self, input_data: Any, params: Dict) -> Dict:
        block = self._resolve_block("opera_connector")
        if block is None:
            return {"status": "error", "error": "opera_connector block unavailable"}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**data, **(params or {})}
        merged.setdefault("action", "fetch")
        return await block.process(merged, {"action": merged["action"]})

    async def _hotel_trigger(self, input_data: Any, params: Dict) -> Dict:
        block = self._resolve_block("hotel_trigger")
        if block is None:
            return {"status": "error", "error": "hotel_trigger block unavailable"}
        data = input_data if isinstance(input_data, dict) else {}
        return await block.process(data, params or {})
