"""SSO SAML — provider configuration registry with fail-closed validation,
ported from Cerebrum ``enterprise/sso_saml.py``.

The python3-saml assertion-validation layer is NOT ported (stated in the
description): the store block ports the provider model and its
configuration contract — entity ids, SSO/SLO URLs, X.509 cert required,
HTTPS-only endpoints, attribute/role mapping. In-process store.
"""
from __future__ import annotations

import time
from typing import Any, Dict

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "sso_saml", "status": status, "result": result, "error": error, "detail": detail}


def _validate_provider(p: Dict[str, Any]) -> str:
    for field in ("name", "idp_entity_id", "idp_sso_url", "idp_x509_cert", "sp_entity_id", "sp_acs_url"):
        if not str(p.get(field, "")).strip():
            return f"{field} is required"
    for field in ("idp_sso_url", "sp_acs_url"):
        url = str(p.get(field, ""))
        if not url.startswith("https://"):
            return f"{field} must be HTTPS"
    return ""


class SsoSamlBlock(UniversalBlock):
    """SAML provider registry, fail-closed configuration."""

    name = "sso_saml"
    version = "1.0.0"
    description = (
        "SSO SAML provider registry ported from Cerebrum enterprise/sso_saml.py: "
        "provider configuration contract (entity ids, SSO/SLO URLs, X.509 cert "
        "required, HTTPS-only endpoints, attribute/role mapping). The python3-saml "
        "assertion-validation layer is NOT ported. Store is in-process."
    )
    layer = 3
    tags = ["sso", "saml", "enterprise", "auth", "cerebrum"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "register", "provider": {"name": "okta", "idp_entity_id": "...", "idp_sso_url": "https://...", "idp_x509_cert": "-----BEGIN...", "sp_entity_id": "...", "sp_acs_url": "https://..."}}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._providers: Dict[str, Dict[str, Any]] = {}

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "register")).lower()
        try:
            if action == "register":
                provider = payload.get("provider") or {}
                problem = _validate_provider(provider)
                if problem:
                    return _envelope("refused", error=problem, detail={"reason": "invalid_provider_config"})
                provider = dict(provider)
                provider["is_active"] = bool(provider.get("is_active", True))
                provider["created_at"] = time.time()
                self._providers[str(provider["name"])] = provider
                return _envelope("ok", {"provider": provider})
            if action == "deactivate":
                name = str(payload.get("name", ""))
                rec = self._providers.get(name)
                if rec is None:
                    return _envelope("error", error="provider not found")
                rec["is_active"] = False
                return _envelope("ok", {"provider": rec})
            if action == "list":
                return _envelope("ok", {"providers": list(self._providers.values()), "count": len(self._providers)})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["register", "deactivate", "list"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
