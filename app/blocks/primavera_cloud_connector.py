"""Primavera Cloud OAuth2 ETL connector — HONEST STUB (no donor exists on disk).

Declared surface: OAuth2 token acquisition and read-only project-data ETL.
No donor adapter exists on disk, so NO OAuth2 request and NO ETL call is
implemented in this block: oauth_token and etl fail closed with a
structured refusal — never a fabricated token, never fabricated project
rows. Unconfigured and configured calls refuse identically until a real
adapter is ported from a donor.
"""
from __future__ import annotations

from typing import Any, Dict

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "primavera_cloud_connector",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


CONFIG_KEYS = [
    "primavera_base_url",
    "primavera_client_id",
    "primavera_client_secret",
    "primavera_username",
    "primavera_password",
]


class PrimaveraCloudConnectorBlock(UniversalBlock):
    """Primavera Cloud OAuth2 ETL connector surface — honest stub, fail closed."""

    name = "primavera_cloud_connector"
    version = "1.0.0"
    description = (
        "honest-stub — Primavera Cloud OAuth2 ETL connector, no donor — honest "
        "stub. No donor adapter exists on disk: no OAuth2 token request and no "
        "ETL call is implemented; oauth_token and etl fail closed with a "
        "structured refusal (never a fabricated token, never fabricated "
        "project rows), whether or not credentials are configured."
    )
    layer = 2
    tags = ["connector", "primavera", "oauth2", "etl", "construction", "honest-stub"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"action": "etl", "resource": "projects"}',
            "multiline": True,
        },
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}]},
    }

    def _configured(self) -> Dict[str, Any]:
        missing = [k for k in CONFIG_KEYS if not str(self.config.get(k, "")).strip()]
        return {"configured": not missing, "missing": missing}

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "status")).lower()
        try:
            if action == "status":
                state = self._configured()
                return _envelope("ok", {
                    "provenance": "honest-stub",
                    "donor": "no donor — honest stub",
                    "implemented": False,
                    "declared_surface": ["oauth2_token", "project_etl"],
                    **state,
                })
            if action == "capabilities":
                return _envelope("ok", {
                    "supported_actions": ["status", "capabilities", "oauth_token", "etl"],
                    "implemented": [],
                    "note": "OAuth2 + ETL fail closed until a real adapter is ported from a donor",
                })
            if action == "oauth_token":
                return self._refuse("oauth_token", payload)
            if action == "etl":
                return self._refuse("etl", payload)
            return _envelope(
                "error",
                error=f"unknown action: {action}",
                detail={"known": ["status", "capabilities", "oauth_token", "etl"]},
            )
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    def _refuse(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        state = self._configured()
        surface = "OAuth2 token" if action == "oauth_token" else "Primavera project ETL"
        if not state["configured"]:
            return _envelope(
                "refused",
                error=f"Primavera Cloud is not configured; refusing to fabricate a {surface}",
                detail={"action": action, "missing": state["missing"]},
            )
        return _envelope(
            "refused",
            error=(
                f"no donor adapter exists — {surface} is not implemented; "
                f"refusing to fabricate data"
            ),
            detail={"action": action, "implemented": False, "provenance": "honest-stub"},
        )
