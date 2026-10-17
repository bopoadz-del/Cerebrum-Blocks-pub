"""Heal Approval — TTL'd one-time approval, ported from <private-repo>
``resident_engineer/heal/approval.py``.

SQLAlchemy is not ported; the store block keeps approvals in-process with
the donor's exact semantics: SHA-256 digest over (tenant, action,
principal), one-hour TTL, consume-once (replay refused), expired refused.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any, Dict

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "heal_approval", "status": status, "result": result, "error": error, "detail": detail}


_APPROVAL_TTL_S = 3600


def heal_approval_digest(*, tenant_id: str, action_id: str, principal_id: str) -> str:
    payload = f"{tenant_id}:{action_id}:{principal_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class HealApprovalBlock(UniversalBlock):
    """Resident-engineer heal approvals: TTL'd, one-time, digest-validated."""

    name = "heal_approval"
    version = "1.0.0"
    description = (
        "TTL'd one-time heal approval ported from <private-repo> resident_engineer/"
        "heal/approval.py: SHA-256 digest over (tenant, action, principal), one-hour "
        "TTL, consume-once with replay refusal. Approval store is in-process."
    )
    layer = 3
    tags = ["governance", "approval", "steward", "resident-engineer"]
    requires = []

    default_config = {"ttl_seconds": _APPROVAL_TTL_S}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "create", "tenant_id": "t1", "principal_id": "u1", "action_id": "heal-x"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._approvals: Dict[str, Dict[str, Any]] = {}

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "create")).lower()
        try:
            if action == "create":
                return self._create(payload)
            if action == "consume":
                return self._consume(payload)
            if action == "digest":
                return _envelope("ok", {"digest": heal_approval_digest(
                    tenant_id=str(payload.get("tenant_id", "")),
                    action_id=str(payload.get("action_id", "")),
                    principal_id=str(payload.get("principal_id", "")),
                )})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["create", "consume", "digest"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    def _create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tenant_id = str(payload.get("tenant_id", ""))
        principal_id = str(payload.get("principal_id", ""))
        action_id = str(payload.get("action_id", ""))
        if not (tenant_id and principal_id and action_id):
            return _envelope("error", error="tenant_id, principal_id and action_id are required")
        approval_id = str(uuid.uuid4())
        record = {
            "approval_id": approval_id,
            "tenant_id": tenant_id,
            "principal_id": principal_id,
            "action_id": action_id,
            "digest": heal_approval_digest(tenant_id=tenant_id, action_id=action_id, principal_id=principal_id),
            "expires_at": time.time() + float(payload.get("ttl_seconds", self.default_config["ttl_seconds"])),
            "consumed": False,
        }
        self._approvals[approval_id] = record
        return _envelope("ok", {"approval": record})

    def _consume(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        approval_id = str(payload.get("approval_id", ""))
        record = self._approvals.get(approval_id)
        if record is None:
            return _envelope("refused", error="approval not found", detail={"approval_id": approval_id})
        if record["consumed"]:
            return _envelope("refused", error="approval already consumed (replay refused)", detail={"approval_id": approval_id})
        if time.time() > record["expires_at"]:
            return _envelope("refused", error="approval expired", detail={"approval_id": approval_id, "expires_at": record["expires_at"]})
        for field in ("tenant_id", "principal_id", "action_id"):
            if str(payload.get(field, "")) != record[field]:
                return _envelope("refused", error=f"approval {field} mismatch", detail={"approval_id": approval_id})
        record["consumed"] = True
        record["consumed_at"] = time.time()
        return _envelope("ok", {"approval": record, "consumed": True})
