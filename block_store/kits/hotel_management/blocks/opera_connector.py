"""Oracle Opera PMS connector — fail-closed live adapter with a real normaliser.

Built on the hotelops-v2 pattern (connectors/base.py): a deployment without
live Opera credentials runs in ``mock_unavailable`` mode — fetch FAILS
CLOSED with a structured refusal envelope and NEVER fabricates operational
data. With ``opera_api_url`` + ``opera_api_key`` + ``opera_app_key``
configured, authenticate() performs the app-key/API-key handshake and
fetch_raw() pulls the requested resource over the Opera REST surface.

The normaliser is real in both modes: Opera reservation / folio / room /
profile shapes map onto the canonical hotel taxonomy so downstream blocks
(and the /v1/connectors/hotel/opera endpoint) see one event vocabulary.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.blocks.core.base_connector import BaseConnector


class OperaConnectorBlock(BaseConnector):
    """Oracle Opera hotel PMS connector (live-capable, fail-closed default)."""

    name = "opera_connector"
    version = "1.0.0"
    description = (
        "Oracle Opera PMS connector: app-key/API-key auth, REST fetch, and a "
        "canonical hotel-event normaliser. Fail-closed mock_unavailable mode "
        "when no live credentials are configured — no fabricated data."
    )
    layer = 3
    tags = ["hotel", "connector", "opera", "pms"]
    connector_source = "opera_pms"

    default_config: Dict[str, Any] = {
        "opera_api_url": "",
        "opera_api_key": "",
        "opera_app_key": "",
        "opera_hotel_id": "",
    }

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "fetch", "resource": "reservations"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "event", "type": "json", "label": "Connector Event"}]},
        "params": [
            {"name": "action", "type": "select", "label": "Action", "options": ["fetch", "auth", "health"], "default": "fetch"},
        ],
        "quick_actions": [],
    }

    def _live_config(self) -> Optional[Tuple[str, str, str]]:
        url = str(self.config.get("opera_api_url") or "").strip()
        key = str(self.config.get("opera_api_key") or "").strip()
        app = str(self.config.get("opera_app_key") or "").strip()
        if url and key and app:
            return url, key, app
        return None

    def _unavailable_envelope(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """The MockLevel.MOCK_UNAVAILABLE envelope: refusal, never data."""
        resource = input_data.get("resource", "reservations") if isinstance(input_data, dict) else "reservations"
        return {
            "system": self.connector_source,
            "available": False,
            "mock_level": "mock_unavailable",
            "resource": resource,
            "data": [],
            "refusal": (
                "opera_pms has no live integration in this deployment. "
                "No operational data is fabricated."
            ),
        }

    async def authenticate(self) -> Dict[str, Any]:
        cfg = self._live_config()
        if cfg is None:
            return {
                "authenticated": False,
                "method": "mock_unavailable",
                "refusal": (
                    "opera_pms has no live integration in this deployment. "
                    "No operational data is fabricated."
                ),
            }
        self._auth_headers = {
            "x-app-key": cfg[2],
            "x-hotelid": str(self.config.get("opera_hotel_id") or ""),
            "Authorization": f"Apikey {cfg[1]}",
        }
        return {"authenticated": True, "method": "apikey", "endpoint": cfg[0]}

    async def fetch_raw(self, input_data: Any, params: Dict) -> Any:
        cfg = self._live_config()
        if cfg is None:
            # Unreachable through process() (auth refuses first), but kept
            # fail-closed for direct callers.
            return self._unavailable_envelope(input_data or {})

        import httpx

        data = input_data if isinstance(input_data, dict) else {}
        resource = str(data.get("resource") or "reservations").strip()
        url = cfg[0].rstrip("/") + f"/crm/v1/{resource}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=getattr(self, "_auth_headers", {}))
            resp.raise_for_status()
            return resp.json()

    def normalize(self, raw: Any, params: Optional[Dict] = None, input_data: Any = None) -> Any:
        """Map Opera payloads onto the canonical hotel event taxonomy.

        The refusal envelope passes through as an unavailable event so the
        envelope contract stays intact in mock mode.
        """
        from app.core.connector_events import ConnectorEvent

        payload = raw if isinstance(raw, dict) else {"data": raw}
        if payload.get("available") is False:
            return ConnectorEvent(
                event_id="opera-unavailable",
                source=self.connector_source,
                event_type="connector.unavailable",
                payload=payload,
                normalized_data={"available": False, "refusal": payload.get("refusal", "")},
                tags=list(self.tags),
            )

        resource = payload.get("resource") or str((params or {}).get("resource") or "reservations")
        records = payload.get("data") or payload.get("items") or []
        normalized: Dict[str, Any] = {"resource": resource, "records": []}
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            kind = str(record.get("type") or record.get("reservationType") or resource).lower()
            mapping = {
                "reservation": "reservation",
                "reservations": "reservation",
                "folio": "folio_posting",
                "guest_folio": "folio_posting",
                "room": "room_status",
                "rooms": "room_status",
                "profile": "guest_profile",
            }
            normalized["records"].append(
                {
                    "canonical_event": mapping.get(kind, kind or "opera_record"),
                    "reservation_id": record.get("confirmationNumber") or record.get("reservationId"),
                    "room": record.get("roomNumber") or record.get("room"),
                    "guest": record.get("guestName") or record.get("profileName"),
                    "arrival": record.get("arrivalDate"),
                    "departure": record.get("departureDate"),
                    "status": record.get("status") or record.get("roomStatus"),
                    "raw": record,
                }
            )
        from datetime import datetime, timezone
        from uuid import uuid4

        return ConnectorEvent(
            event_id=str(uuid4())[:12],
            source=self.connector_source,
            event_type=(params or {}).get("event_type", "connector.fetch"),
            timestamp=datetime.now(timezone.utc),
            payload=payload,
            normalized_data=normalized,
            tags=list(self.tags),
        )
