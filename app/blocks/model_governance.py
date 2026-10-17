"""Model governance â€” AI use-case risk-tier register and model validation
records, ported from <private-repo> ``governance/service.py``
(create_ai_use_case / list_ai_use_cases / get_ai_use_case /
create_model_governance_record / approve_model).

The SQLAlchemy layer is not ported; the rules are, exactly:
risk_tier must be in {low, medium, high}, use-case status in
{draft, active, retired}, validation_status in {pending, approved, failed},
a governance record may only reference an existing AI use case, and
approve_model only acts on a record that exists (pending -> approved).
Fail-loud on every invalid transition. In-process store.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock

_VALID_RISK_TIERS = {"low", "medium", "high"}
_VALID_USE_CASE_STATUSES = {"draft", "active", "retired"}
_VALID_VALIDATION_STATUSES = {"pending", "approved", "failed"}


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "model_governance", "status": status, "result": result, "error": error, "detail": detail}


class ModelGovernanceBlock(UniversalBlock):
    """AI risk-tier register + model validation records (FinanceOps donor)."""

    name = "model_governance"
    version = "1.0.0"
    description = (
        "real: AI use-case risk-tier register and model validation records "
        "ported from <private-repo> backend/app/governance/service.py "
        "(create_ai_use_case, list_ai_use_cases, create_model_governance_record, "
        "approve_model). risk_tier is validated against {low, medium, high}, "
        "validation_status against {pending, approved, failed}, and records "
        "may only reference existing use cases. Invalid inputs fail loud. "
        "In-process store (SQLAlchemy not ported)."
    )
    layer = 3
    tags = ["governance", "ai-governance", "risk-tier", "model-validation", "finance_ops"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "create_ai_use_case", "tenant_id": "t1", "use_case_name": "invoice extraction", "model_name": "ocr-1", "risk_tier": "medium"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._use_cases: Dict[str, Dict[str, Any]] = {}
        self._records: Dict[str, Dict[str, Any]] = {}

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "create_ai_use_case")).lower()
        try:
            if action == "create_ai_use_case":
                return self._create_ai_use_case(payload)
            if action == "list_ai_use_cases":
                return self._list_ai_use_cases(payload)
            if action == "get_ai_use_case":
                return self._get_ai_use_case(payload)
            if action == "create_model_governance_record":
                return self._create_model_governance_record(payload)
            if action == "approve_model":
                return self._approve_model(payload)
            if action == "list_model_governance_records":
                return self._list_records(payload)
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["create_ai_use_case", "list_ai_use_cases", "get_ai_use_case", "create_model_governance_record", "approve_model", "list_model_governance_records"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    # -- internals ---------------------------------------------------------

    def _create_ai_use_case(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        risk_tier = str(payload.get("risk_tier", ""))
        if risk_tier not in _VALID_RISK_TIERS:
            return _envelope("error", error="Invalid risk_tier", detail={"risk_tier": risk_tier, "valid": sorted(_VALID_RISK_TIERS)})
        status = str(payload.get("status", "draft"))
        if status not in _VALID_USE_CASE_STATUSES:
            return _envelope("error", error="Invalid status", detail={"status": status, "valid": sorted(_VALID_USE_CASE_STATUSES)})
        tenant_id = str(payload.get("tenant_id", ""))
        if not tenant_id:
            return _envelope("error", error="tenant_id is required")
        use_case_name = str(payload.get("use_case_name", ""))
        model_name = str(payload.get("model_name", ""))
        if not use_case_name or not model_name:
            return _envelope("error", error="use_case_name and model_name are required")
        use_case_id = f"uc-{len(self._use_cases) + 1}"
        self._use_cases[use_case_id] = {
            "id": use_case_id,
            "tenant_id": tenant_id,
            "project_id": payload.get("project_id"),
            "use_case_name": use_case_name,
            "description": payload.get("description"),
            "model_name": model_name,
            "risk_tier": risk_tier,
            "status": status,
        }
        return _envelope("ok", {"use_case": self._use_cases[use_case_id]})

    def _list_ai_use_cases(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        rows = [u for u in self._use_cases.values() if str(payload.get("tenant_id", "")) in ("", str(u.get("tenant_id", "")))]
        return _envelope("ok", {"use_cases": rows, "count": len(rows)})

    def _get_ai_use_case(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        use_case = self._use_cases.get(str(payload.get("use_case_id", "")))
        if use_case is None:
            return _envelope("error", error="AI use case not found", detail={"use_case_id": payload.get("use_case_id")})
        return _envelope("ok", {"use_case": use_case})

    def _create_model_governance_record(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ai_use_case_id = str(payload.get("ai_use_case_id", ""))
        if ai_use_case_id not in self._use_cases:
            return _envelope("error", error="AI use case not found", detail={"ai_use_case_id": ai_use_case_id})
        validation_status = str(payload.get("validation_status", "pending"))
        if validation_status not in _VALID_VALIDATION_STATUSES:
            return _envelope("error", error="Invalid validation_status", detail={"validation_status": validation_status, "valid": sorted(_VALID_VALIDATION_STATUSES)})
        model_version = str(payload.get("model_version", ""))
        if not model_version:
            return _envelope("error", error="model_version is required")
        record_id = f"mg-{len(self._records) + 1}"
        self._records[record_id] = {
            "id": record_id,
            "tenant_id": str(payload.get("tenant_id", "")),
            "ai_use_case_id": ai_use_case_id,
            "model_version": model_version,
            "validation_status": validation_status,
            "validation_notes": payload.get("validation_notes"),
        }
        return _envelope("ok", {"record": self._records[record_id]})

    def _approve_model(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        record_id = str(payload.get("record_id", ""))
        record = self._records.get(record_id)
        if record is None:
            return _envelope("error", error="Model governance record not found", detail={"record_id": record_id})
        record["validation_status"] = "approved"
        if payload.get("notes") is not None:
            record["validation_notes"] = payload.get("notes")
        return _envelope("ok", {"record": record})

    def _list_records(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        rows = [r for r in self._records.values() if str(payload.get("tenant_id", "")) in ("", str(r.get("tenant_id", "")))]
        return _envelope("ok", {"records": rows, "count": len(rows)})
