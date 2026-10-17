"""Canonical FinanceOps data model and record validation block."""

from __future__ import annotations

from typing import Any, Dict, List

from app.core.finance_ops import (
    CANONICAL_DIMENSIONS, CANONICAL_FACT_TYPES, CANONICAL_FIELDS,
    normalize_common_values, normalize_record_keys, stable_digest,
    validate_canonical_record,
)
from app.core.typed_block import TypedBlock
from app.core.http_errors import error_kind


class FinanceCanonicalModelBlock(TypedBlock):
    """Expose and enforce the governed FinanceOps canonical record contract."""

    name = "finance_canonical_model"
    version = "1.0.0"
    description = (
        "Canonical FinanceOps dimensions, fact types, normalization, and deterministic "
        "record validation for ERP, CRM, HCM, planning, and project-cost data."
    )
    layer = 3
    tags = ["domain", "finance_ops", "data_model", "governance", "deterministic"]
    requires: List[str] = []
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string"}, "record_type": {"type": "string"},
            "record": {"type": "object"}, "records": {"type": "array"},
        },
    }
    output_schema = {"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]}
    accepted_input_types = ["JSON"]
    produced_output_types = ["FinanceCanonicalModel"]
    default_config = {"model_version": "finance_ops.v1"}
    ui_schema = {
        "input": {"type": "json", "multiline": True}, "output": {"type": "json"},
        "quick_actions": [
            {"icon": "", "label": "Show Model", "prompt": "Show the FinanceOps canonical model"},
            {"icon": "", "label": "Validate Record", "prompt": "Validate a canonical finance record"},
        ],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        data = {**(params or {}), **(input_data if isinstance(input_data, dict) else {})}
        operation = data.get("operation") or data.get("action") or "schema"
        try:
            if operation == "schema":
                return self._schema()
            if operation == "normalize_record":
                return self._normalize_record(data)
            if operation == "validate_record":
                return self._validate_record(data)
            if operation == "validate_dataset":
                return self._validate_dataset(data)
        except (TypeError, ValueError) as exc:
            return {"status": "validation_error", "operation": operation, "error": str(exc), "error_kind": error_kind(exc)}
        return {
            "status": "unsupported", "operation": operation,
            "error": f"Unknown operation: {operation}",
            "available_operations": ["schema", "normalize_record", "validate_record", "validate_dataset"],
        }

    def _schema(self) -> Dict[str, Any]:
        payload = {
            "model_version": self.config.get("model_version", "finance_ops.v1"),
            "dimensions": list(CANONICAL_DIMENSIONS),
            "fact_types": {key: {"required_fields": list(required)} for key, required in CANONICAL_FACT_TYPES.items()},
            "canonical_fields": list(CANONICAL_FIELDS),
            "money_serialization": "fixed_point_string_4dp",
            "decision_policy": "advisory_only_human_approval_required",
        }
        return {"status": "success", "operation": "schema", **payload, "schema_digest": stable_digest(payload)}

    @staticmethod
    def _normalized(data: Dict[str, Any]) -> Dict[str, Any]:
        record = data.get("record")
        if not isinstance(record, dict):
            raise ValueError("record must be an object")
        record_type = str(data.get("record_type") or record.get("record_type") or "").strip()
        if not record_type:
            raise ValueError("record_type is required")
        field_map = data.get("field_map") if isinstance(data.get("field_map"), dict) else {}
        normalized = normalize_common_values(normalize_record_keys(record, field_map))
        normalized["record_type"] = record_type
        return normalized

    def _normalize_record(self, data: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self._normalized(data)
        issues = validate_canonical_record(normalized["record_type"], normalized)
        return {
            "status": "success" if not issues else "validation_error",
            "operation": "normalize_record", "record": normalized, "issues": issues,
            "record_digest": stable_digest(normalized),
        }

    def _validate_record(self, data: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self._normalized(data)
        issues = validate_canonical_record(normalized["record_type"], normalized)
        return {
            "status": "success" if not issues else "validation_error",
            "operation": "validate_record", "valid": not issues,
            "record": normalized, "issues": issues, "record_digest": stable_digest(normalized),
        }

    @staticmethod
    def _validate_dataset(data: Dict[str, Any]) -> Dict[str, Any]:
        records = data.get("records")
        if not isinstance(records, list):
            raise ValueError("records must be an array")
        default_type = str(data.get("record_type") or "").strip()
        results, valid_count = [], 0
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                results.append({"row_number": index, "valid": False, "issues": [{"severity": "error", "code": "record_not_object", "message": "Record must be an object"}]})
                continue
            record_type = str(record.get("record_type") or default_type).strip()
            normalized = normalize_common_values(normalize_record_keys(record))
            normalized["record_type"] = record_type
            issues = validate_canonical_record(record_type, normalized)
            valid_count += int(not issues)
            results.append({"row_number": index, "valid": not issues, "record": normalized, "issues": issues})
        return {
            "status": "success" if valid_count == len(records) else "validation_error",
            "operation": "validate_dataset", "record_count": len(records),
            "valid_count": valid_count, "invalid_count": len(records) - valid_count,
            "results": results, "dataset_digest": stable_digest(records),
        }
