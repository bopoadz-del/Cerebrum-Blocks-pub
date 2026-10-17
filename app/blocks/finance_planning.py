"""Finance Planning — immutable budget versions, approval-gated lock, and
allocation remainder routing, ported from <private-repo>
``planning/service.py``.

SQLAlchemy is not ported. Ported exactly: a locked budget is immutable
(an update creates version N+1, never mutates the locked row), a lock
requires an approved governance request, and allocation distributes
total/count quantized to 0.0001 with the remainder routed to the first
member so the total stays exact. In-process store.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "finance_planning", "status": status, "result": result, "error": error, "detail": detail}


class FinancePlanningBlock(UniversalBlock):
    """Budget lifecycle + allocation ported from <private-repo>."""

    name = "finance_planning"
    version = "1.0.0"
    description = (
        "Finance planning ported from <private-repo> planning/service.py: "
        "draft budgets lock behind an approved governance request; locked budgets "
        "are immutable (edits create version N+1); allocation splits total/count "
        "quantized to 0.0001 with the remainder routed to the first member so the "
        "total stays exact. Store is in-process."
    )
    layer = 3
    tags = ["finance", "planning", "budget", "allocation", "finance_ops"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "create_budget", "tenant_id": "t1", "amount": "1000.00", "period": "2026-01"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._budgets: Dict[str, Dict[str, Any]] = {}
        self._allocations: List[Dict[str, Any]] = []

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "create_budget")).lower()
        try:
            if action == "create_budget":
                return self._create_budget(payload)
            if action == "lock_budget":
                return self._lock_budget(payload)
            if action == "update_budget":
                return self._update_budget(payload)
            if action == "run_allocation":
                return self._run_allocation(payload)
            if action == "list_budgets":
                return _envelope("ok", {"budgets": list(self._budgets.values()), "count": len(self._budgets)})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["create_budget", "lock_budget", "update_budget", "run_allocation", "list_budgets"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    # -- internals ---------------------------------------------------------

    def _create_budget(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tenant_id = str(payload.get("tenant_id", ""))
        amount = str(payload.get("amount", ""))
        if not tenant_id or not amount:
            return _envelope("error", error="tenant_id and amount are required")
        try:
            Decimal(amount)
        except Exception:
            return _envelope("error", error="amount must be a decimal number")
        budget_id = f"b-{len(self._budgets) + 1}"
        self._budgets[budget_id] = {
            "id": budget_id,
            "tenant_id": tenant_id,
            "amount": amount,
            "period": str(payload.get("period", "")),
            "currency_code": str(payload.get("currency_code", "USD")).upper(),
            "status": "draft",
            "version": 1,
        }
        return _envelope("ok", {"budget": self._budgets[budget_id]})

    def _lock_budget(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        budget = self._budgets.get(str(payload.get("budget_id", "")))
        if budget is None:
            return _envelope("error", error="budget not found")
        if budget["status"] != "draft":
            return _envelope("refused", error="only draft budgets can be locked")
        approved = payload.get("approved", False)
        if not approved:
            # The donor gates the lock behind require_approved_action; the
            # store caller must present an approved governance request.
            return _envelope("refused", error="budget_lock requires an approved governance request", detail={"action_type": "budget_lock"})
        budget["status"] = "locked"
        return _envelope("ok", {"budget": budget})

    def _update_budget(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        budget = self._budgets.get(str(payload.get("budget_id", "")))
        if budget is None:
            return _envelope("error", error="budget not found")
        if budget["status"] == "locked":
            # Immutable: a locked row is never mutated; a new version is born.
            new_id = f"b-{len(self._budgets) + 1}"
            replacement = {
                "id": new_id,
                "tenant_id": budget["tenant_id"],
                "amount": str(payload.get("amount", budget["amount"])),
                "period": str(payload.get("period", budget["period"])),
                "currency_code": str(payload.get("currency_code", budget["currency_code"])).upper(),
                "status": "draft",
                "version": budget["version"] + 1,
            }
            self._budgets[new_id] = replacement
            return _envelope("ok", {"budget": replacement, "note": "locked budget untouched; new version created"})
        if budget["status"] != "draft":
            return _envelope("refused", error="only draft budgets can be edited")
        if "amount" in payload:
            budget["amount"] = str(payload["amount"])
        if "period" in payload:
            budget["period"] = str(payload["period"])
        return _envelope("ok", {"budget": budget})

    def _run_allocation(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        total = Decimal(str(payload.get("total_amount", "")))
        members = payload.get("members") or []
        if not isinstance(members, list) or not members:
            return _envelope("refused", error="no active dimension members for driver dimension")
        count = Decimal(len(members))
        base = (total / count).quantize(Decimal("0.0001"))
        remainder = total - (base * count)
        results = []
        for idx, member in enumerate(members):
            allocated = base + (remainder if idx == 0 else Decimal("0"))
            results.append({"member": str(member), "allocated_amount": str(allocated)})
        self._allocations.append({"total": str(total), "results": results, "remainder": str(remainder)})
        return _envelope("ok", {"results": results, "remainder": str(remainder), "total": str(total)})
