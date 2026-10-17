"""BaseConnector — shared auth/fetch/normalize pattern for external integrations."""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from app.core.connector_events import ConnectorEvent
from app.core.universal_base import UniversalBlock


class BaseConnector(UniversalBlock):
    """Universal connector block with auth → fetch → normalize → envelope."""

    layer = 2
    tags = ["connector", "integration"]
    requires: list = []

    connector_source: str = "unknown"
    default_config: Dict = {}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"action": "fetch", "resource": "patients"}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "event", "type": "json", "label": "Connector Event"},
                {"name": "status", "type": "text", "label": "Status"},
            ],
        },
        "params": [
            {
                "name": "action",
                "type": "select",
                "label": "Action",
                "options": ["fetch", "auth", "health"],
                "default": "fetch",
            },
        ],
        "quick_actions": [],
    }

    async def authenticate(self) -> Dict[str, Any]:
        """Override to perform OAuth/API-key auth. Default: no-op success."""
        return {"authenticated": True, "method": "none"}

    @abstractmethod
    async def fetch_raw(self, input_data: Any, params: Dict) -> Any:
        """Pull raw payload from external system."""

    def normalize(
        self, raw: Any, params: Optional[Dict] = None, input_data: Any = None
    ) -> ConnectorEvent:
        """Map raw fetch result to a ConnectorEvent. Override for domain shaping."""
        event_type = (params or {}).get("event_type", "connector.fetch")
        payload = raw if isinstance(raw, dict) else {"data": raw}
        return ConnectorEvent(
            event_id=str(uuid4())[:12],
            source=self.connector_source,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            payload=payload,
            normalized_data=payload,
            tags=list(getattr(self, "tags", [])),
        )

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        action = params.get("action") or data.get("action", "fetch")

        if action == "health":
            return {
                "status": "healthy",
                "connector": self.connector_source,
                "block": self.name,
                "version": self.version,
            }

        if action == "auth":
            auth = await self.authenticate()
            return {"status": "success", "auth": auth}

        if action == "fetch":
            auth = await self.authenticate()
            if not auth.get("authenticated"):
                return {"status": "error", "error": "Authentication failed", "auth": auth}
            raw = await self.fetch_raw(data, params)
            event = self.normalize(raw, params, data)
            return {
                "status": "success",
                "event": event.model_dump(mode="json"),
                "connector": self.connector_source,
            }

        return {"status": "error", "error": f"Unknown action: {action}"}
