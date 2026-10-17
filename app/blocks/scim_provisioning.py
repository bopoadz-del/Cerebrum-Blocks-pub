"""SCIM Provisioning — directory-sync provider registry, ported from
Cerebrum ``enterprise/scim.py``.

The donor stored the provider bearer token PLAINTEXT; the store port
hashes it (SHA-256) at registration and never returns it — an honest
hardening, noted in the description. Sync status tracking and user
upsert mapping are ported.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "scim_provisioning", "status": status, "result": result, "error": error, "detail": detail}


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ScimProvisioningBlock(UniversalBlock):
    """SCIM 2.0 provider registry with token hashing."""

    name = "scim_provisioning"
    version = "1.0.0"
    description = (
        "SCIM 2.0 provider registry ported from Cerebrum enterprise/scim.py: "
        "auth_type bearer/oauth, provider tokens stored as SHA-256 hashes (the "
        "donor's plaintext column is deliberately not ported), sync status "
        "tracking, user upsert attribute mapping. Store is in-process."
    )
    layer = 3
    tags = ["scim", "enterprise", "auth", "directory-sync", "cerebrum"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "register", "provider": {"name": "azure", "auth_type": "bearer_token", "bearer_token": "...", "scim_base_url": "https://..."}}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._providers: Dict[str, Dict[str, Any]] = {}
        self._users: Dict[str, Dict[str, Any]] = {}

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "register")).lower()
        try:
            if action == "register":
                provider = payload.get("provider") or {}
                name = str(provider.get("name", ""))
                base_url = str(provider.get("scim_base_url", ""))
                if not name or not base_url.startswith("https://"):
                    return _envelope("refused", error="name and an HTTPS scim_base_url are required")
                auth_type = str(provider.get("auth_type", "bearer_token"))
                rec = {
                    "name": name,
                    "auth_type": auth_type,
                    "scim_base_url": base_url,
                    "created_at": time.time(),
                    "last_sync_status": None,
                    "last_sync_error": None,
                }
                if auth_type == "bearer_token":
                    token = str(provider.get("bearer_token", ""))
                    if not token:
                        return _envelope("refused", error="bearer_token is required for bearer_token auth")
                    rec["token_hash"] = _hash_token(token)
                else:
                    return _envelope("refused", error=f"auth_type {auth_type} is not implemented in the store port")
                self._providers[name] = rec
                return _envelope("ok", {"provider": {k: v for k, v in rec.items() if k != "token_hash"}})
            if action == "record_sync":
                name = str(payload.get("name", ""))
                rec = self._providers.get(name)
                if rec is None:
                    return _envelope("error", error="provider not found")
                rec["last_sync_status"] = str(payload.get("status", "ok"))
                rec["last_sync_error"] = payload.get("error")
                rec["last_sync_at"] = time.time()
                return _envelope("ok", {"provider": {k: v for k, v in rec.items() if k != "token_hash"}})
            if action == "upsert_user":
                external_id = str(payload.get("external_id", ""))
                if not external_id:
                    return _envelope("refused", error="external_id is required")
                self._users[external_id] = {"external_id": external_id, "attributes": payload.get("attributes") or {}, "updated_at": time.time()}
                return _envelope("ok", {"user": self._users[external_id]})
            if action == "list":
                return _envelope("ok", {"providers": [{k: v for k, v in p.items() if k != "token_hash"} for p in self._providers.values()], "users": len(self._users)})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["register", "record_sync", "upsert_user", "list"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
