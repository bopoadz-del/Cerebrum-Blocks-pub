"""Clinical trigger stub — fires on FHIR observation thresholds (skeleton)."""

from __future__ import annotations

from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock


class ClinicalTriggerBlock(UniversalBlock):
    """Stub for clinical alert routing — extend with vitals thresholds."""

    name = "clinical_trigger"
    version = "0.1.0-skeleton"
    description = "Evaluate FHIR observations and emit clinical alerts (stub)"
    layer = 3
    tags = ["medical", "trigger", "clinical", "stub"]
    requires: List[str] = []

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"observations": []}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "alerts", "type": "json", "label": "Alerts"}]},
        "params": [
            {
                "name": "action",
                "type": "select",
                "label": "Action",
                "options": ["evaluate", "health"],
                "default": "evaluate",
            },
        ],
        "quick_actions": [],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        action = params.get("action", "evaluate")
        if action == "health":
            return {"status": "healthy", "block": self.name, "stub": True}
        return {
            "status": "success",
            "triggered": False,
            "alerts": [],
            "message": "clinical_trigger stub — implement threshold rules",
        }
