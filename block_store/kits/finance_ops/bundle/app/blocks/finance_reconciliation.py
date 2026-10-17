"""Deterministic FinanceOps reconciliation engine."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from app.core.finance_ops import DEFAULT_TOLERANCE, group_decimal_sum, money_str, stable_digest, to_decimal
from app.core.typed_block import TypedBlock
from app.core.http_errors import error_kind


class FinanceReconciliationBlock(TypedBlock):
    """Reconcile two finance datasets using exact Decimal aggregation."""

    name = "finance_reconciliation"
    version = "1.0.0"
    description = "Source-to-ledger, voucher-to-GL, and GL-to-management reconciliation with governed grouping keys, Decimal tolerance, and evidence digests."
    layer = 3
    tags = ["domain", "finance_ops", "reconciliation", "controls", "deterministic"]
    requires: List[str] = []
    input_schema = {"type": "object", "properties": {"left_records": {"type": "array"}, "right_records": {"type": "array"}, "group_by": {"type": "array"}, "tolerance": {"type": "string"}}}
    output_schema = {"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]}
    accepted_input_types = ["JSON"]
    produced_output_types = ["FinanceReconciliationReport"]
    default_config = {"group_by": ["entity_id", "account_id", "period", "currency"], "amount_field": "amount", "tolerance": "0.01"}
    ui_schema = {"input": {"type": "json", "multiline": True}, "output": {"type": "json"}}

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        data = {**(params or {}), **(input_data if isinstance(input_data, dict) else {})}
        left_records, right_records = data.get("left_records"), data.get("right_records")
        if not isinstance(left_records, list) or not isinstance(right_records, list):
            return {"status": "validation_error", "error": "left_records and right_records must both be arrays"}
        group_by = data.get("group_by") or self.config.get("group_by")
        if not isinstance(group_by, list) or not group_by:
            return {"status": "validation_error", "error": "group_by must be a non-empty array"}
        amount_field = str(data.get("amount_field") or self.config.get("amount_field", "amount"))
        try:
            tolerance = to_decimal(data.get("tolerance", self.config.get("tolerance", DEFAULT_TOLERANCE)), "tolerance")
            left = group_decimal_sum(left_records, group_by, amount_field)
            right = group_decimal_sum(right_records, group_by, amount_field)
        except ValueError as exc:
            return {"status": "validation_error", "error": str(exc), "error_kind": error_kind(exc)}
        matched: List[Dict[str, Any]] = []
        variances: List[Dict[str, Any]] = []
        left_only: List[Dict[str, Any]] = []
        right_only: List[Dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            left_value, right_value = left.get(key), right.get(key)
            key_object = {field: key[index] for index, field in enumerate(group_by)}
            if left_value is None:
                right_only.append({"key": key_object, "left_amount": money_str(0), "right_amount": money_str(right_value), "variance": money_str(-right_value)})
                continue
            if right_value is None:
                left_only.append({"key": key_object, "left_amount": money_str(left_value), "right_amount": money_str(0), "variance": money_str(left_value)})
                continue
            variance = left_value - right_value
            row = {"key": key_object, "left_amount": money_str(left_value), "right_amount": money_str(right_value), "variance": money_str(variance), "within_tolerance": abs(variance) <= tolerance}
            (matched if abs(variance) <= tolerance else variances).append(row)
        left_total = sum(left.values(), Decimal("0"))
        right_total = sum(right.values(), Decimal("0"))
        total_variance = left_total - right_total
        exception_count = len(variances) + len(left_only) + len(right_only)
        evidence = {"group_by": group_by, "amount_field": amount_field, "tolerance": money_str(tolerance), "matched": matched, "variances": variances, "left_only": left_only, "right_only": right_only}
        return {
            "status": "success", "reconciliation_status": "reconciled" if not exception_count else "exceptions",
            "group_by": group_by, "amount_field": amount_field, "tolerance": money_str(tolerance),
            "summary": {"left_record_count": len(left_records), "right_record_count": len(right_records), "left_group_count": len(left), "right_group_count": len(right), "matched_group_count": len(matched), "variance_group_count": len(variances), "left_only_group_count": len(left_only), "right_only_group_count": len(right_only), "exception_count": exception_count},
            "control_totals": {"left_total": money_str(left_total), "right_total": money_str(right_total), "variance": money_str(total_variance), "within_tolerance": abs(total_variance) <= tolerance},
            **evidence, "evidence_digest": stable_digest(evidence),
            "decision_policy": "exceptions_require_human_review",
        }
