"""Governance Gate — fail-closed action approval, ported from
<private-repo> ``governance/service.py`` (require_approved_action).

The SQLAlchemy/FastAPI layers are not ported; the gate itself is:
an action may execute only when an approval request for
(tenant, action_type, target_id) exists and is approved. Anything else
is refused. The approval store is in-process (honest about it — no
database is wired in the Store build).
"""
from __future__ import annotations

import time
from typing import Any, Dict

from app.core.universal_base import UniversalBlock


def _envelope(status: str, result: Any = None, error: str = None, detail: Any = None) -> Dict[str, Any]:
    return {"block_id": "governance_gate", "status": status, "result": result, "error": error, "detail": detail}


class GovernanceGateBlock(UniversalBlock):
    """Fail-closed approval gate: no approved request -> refused."""

    name = "governance_gate"
    version = "1.0.0"
    description = (
        "Fail-closed governance gate ported from <private-repo>: an action "
        "executes only when an approved request exists for (tenant, action_type, "
        "target_id). Approval store is in-process."
    )
    layer = 3
    tags = ["governance", "approval", "fail-closed", "finance_ops"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "require_approved", "tenant_id": "t1", "action_type": "budget_lock", "target_id": "b1"}', "multiline": True},
        "output": {"type": "json", "fields": [
            {"name": "status", "type": "string", "label": "Status"},
            {"name": "result", "type": "json", "label": "Result"},
            {"name": "error", "type": "string", "label": "Error"},
        ]},
    }

    # In-process approval store: tenant -> (action_type, target_id) -> record.
    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._requests: Dict[str, Dict[str, Any]] = {}

    async def process(self, input_data: Any, params: Dict = None) -> Dict[str, Any]:
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "require_approved")).lower()
        try:
            if action == "create_request":
                return self._create(payload)
            if action == "approve":
                return self._approve(payload)
            if action == "require_approved":
                return self._require(payload)
            if action == "list_requests":
                return _envelope("ok", {"requests": list(self._requests.values())})
            return _envelope(
                "error", error=f"unknown action: {action}",
                detail={"known": ["create_request", "approve", "require_approved", "list_requests"]},
            )
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data: Any, params: Dict = None) -> Dict[str, Any]:
        return await self.process(input_data, params)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _key(tenant_id: str, action_type: str, target_id: str) -> str:
        return f"{tenant_id}|{action_type}|{target_id}"

    def _create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tenant_id = str(payload.get("tenant_id", ""))
        action_type = str(payload.get("action_type", ""))
        target_id = str(payload.get("target_id", ""))
        requester = str(payload.get("requester_id", ""))
        if not (tenant_id and action_type and target_id and requester):
            return _envelope("error", error="tenant_id, action_type, target_id and requester_id are required")
        key = self._key(tenant_id, action_type, target_id)
        if key in self._requests:
            return _envelope("error", error="an approval request already exists for this action/target")
        record = {
            "id": key,
            "tenant_id": tenant_id,
            "action_type": action_type,
            "target_id": target_id,
            "requester_id": requester,
            "status": "pending",
            "created_at": time.time(),
        }
        self._requests[key] = record
        return _envelope("ok", {"request": record})

    def _approve(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tenant_id = str(payload.get("tenant_id", ""))
        action_type = str(payload.get("action_type", ""))
        target_id = str(payload.get("target_id", ""))
        approver = str(payload.get("approver_id", ""))
        if not approver:
            return _envelope("error", error="approver_id is required")
        key = self._key(tenant_id, action_type, target_id)
        record = self._requests.get(key)
        if record is None:
            return _envelope("error", error="no approval request exists for this action/target")
        if record["requester_id"] == approver:
            return _envelope("error", error="self-approval is refused")
        record["status"] = "approved"
        record["approved_by"] = approver
        record["approved_at"] = time.time()
        return _envelope("ok", {"request": record})

    def _require(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tenant_id = str(payload.get("tenant_id", ""))
        action_type = str(payload.get("action_type", ""))
        target_id = str(payload.get("target_id", ""))
        if not (tenant_id and action_type and target_id):
            return _envelope("error", error="tenant_id, action_type and target_id are required")
        record = self._requests.get(self._key(tenant_id, action_type, target_id))
        if record is None:
            # Fail-closed: no request -> refused.
            return _envelope("refused", error="action requires an approved request", detail={"reason": "no_request"})
        if record["status"] != "approved":
            return _envelope("refused", error="action requires an approved request", detail={"request_id": record["id"], "status": record["status"]})
        return _envelope("ok", {"approved": True, "request": record})
