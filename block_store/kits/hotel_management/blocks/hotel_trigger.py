"""Hotel trigger stub — guest service / occupancy reactive workflows."""

from __future__ import annotations

from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock


class HotelTriggerBlock(UniversalBlock):
    name = "hotel_trigger"
    version = "0.1.0-skeleton"
    description = "Hotel occupancy and guest-service trigger (stub)"
    layer = 3
    tags = ["hotel", "trigger", "hospitality", "stub"]
    requires: List[str] = []

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"event_type": "queue_threshold"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "triggered", "type": "boolean", "label": "Triggered"}]},
        "params": [
            {"name": "action", "type": "select", "label": "Action", "options": ["evaluate", "health"], "default": "evaluate"},
        ],
        "quick_actions": [],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        if params.get("action") == "health":
            return {"status": "healthy", "block": self.name, "stub": True}
        return {
            "status": "success",
            "triggered": False,
            "workflow_payload": {"trigger": "hotel_event", "stub": True},
        }
