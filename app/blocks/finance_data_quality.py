"""Finance data-quality scoring and exception generation."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from app.core.finance_ops import DEFAULT_TOLERANCE, canonical_period, is_missing, money_str, stable_digest, to_decimal
from app.core.typed_block import TypedBlock
from app.core.http_errors import error_kind


class FinanceDataQualityBlock(TypedBlock):
    """Run deterministic Finance-side controls over canonical records."""

    name = "finance_data_quality"
    version = "1.0.0"
    description = "Finance data-quality controls for required fields, duplicates, currencies, periods, orphan dimensions, and unbalanced journals."
    layer = 3
    tags = ["domain", "finance_ops", "data_quality", "controls", "deterministic"]
    requires: List[str] = []
    input_schema = {"type": "object", "properties": {"records": {"type": "array"}, "required_fields": {"type": "array"}, "master_data": {"type": "object"}}}
    output_schema = {"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]}
    accepted_input_types = ["JSON"]
    produced_output_types = ["FinanceDataQualityReport"]
    default_config = {"allowed_currencies": ["USD", "EUR", "GBP", "SAR", "AED", "AUD", "CAD", "JPY"], "balance_tolerance": "0.01"}
    ui_schema = {"input": {"type": "json", "multiline": True}, "output": {"type": "json"}}

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        data = {**(params or {}), **(input_data if isinstance(input_data, dict) else {})}
        records = data.get("records")
        if not isinstance(records, list):
            return {"status": "validation_error", "error": "records must be an array"}
        required_fields = data.get("required_fields") or ["record_id", "entity_id", "period", "currency"]
        unique_fields = data.get("unique_fields") or ["record_id"]
        allowed_currencies = {str(value).upper() for value in (data.get("allowed_currencies") or self.config.get("allowed_currencies", []))}
        master_data = data.get("master_data") if isinstance(data.get("master_data"), dict) else {}
        try:
            tolerance = to_decimal(data.get("balance_tolerance", self.config.get("balance_tolerance", DEFAULT_TOLERANCE)), "balance_tolerance")
        except ValueError as exc:
            return {"status": "validation_error", "error": str(exc), "error_kind": error_kind(exc)}
        issues = self._row_issues(records, required_fields, allowed_currencies)
        issues += self._duplicate_issues(records, unique_fields)
        issues += self._master_data_issues(records, master_data)
        issues += self._journal_balance_issues(records, data, tolerance)
        severity_counts = {severity: sum(1 for issue in issues if issue["severity"] == severity) for severity in ("critical", "error", "warning", "info")}
        deductions = severity_counts["critical"] * 25 + severity_counts["error"] * 10 + severity_counts["warning"] * 3 + severity_counts["info"]
        score = max(Decimal("0"), Decimal("100") - Decimal(deductions) / max(len(records), 1))
        blocking = severity_counts["critical"] + severity_counts["error"]
        evidence = {"records": records, "issues": issues, "quality_score": format(score.quantize(Decimal("0.01")), "f")}
        return {
            "status": "success" if not blocking else "validation_error",
            "record_count": len(records), "quality_score": evidence["quality_score"],
            "gate": "pass" if not blocking else "fail", "severity_counts": severity_counts,
            "issues": issues,
            "controls_run": ["required_fields", "numeric_amount", "period_format", "currency_format", "duplicate_keys", "master_data_references", "journal_balance"],
            "evidence_digest": stable_digest(evidence),
        }

    @staticmethod
    def _row_issues(records: List[Any], required_fields: Sequence[str], allowed_currencies: set[str]) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        for row_number, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                issues.append({"severity": "critical", "code": "record_not_object", "row_number": row_number, "message": "Record must be an object"})
                continue
            for field in required_fields:
                if is_missing(record.get(field)):
                    issues.append({"severity": "error", "code": "required_field_missing", "row_number": row_number, "field": field, "message": f"Required field '{field}' is missing"})
            if not is_missing(record.get("amount")):
                try:
                    to_decimal(record["amount"], "amount")
                except ValueError as exc:
                    issues.append({"severity": "error", "code": "invalid_amount", "row_number": row_number, "field": "amount", "message": str(exc)})
            if not is_missing(record.get("period")):
                try:
                    canonical_period(record["period"])
                except ValueError as exc:
                    issues.append({"severity": "error", "code": "invalid_period", "row_number": row_number, "field": "period", "message": str(exc)})
            if not is_missing(record.get("currency")):
                currency = str(record["currency"]).upper()
                if len(currency) != 3 or not currency.isalpha():
                    issues.append({"severity": "error", "code": "invalid_currency", "row_number": row_number, "field": "currency", "message": "currency must be a three-letter code"})
                elif allowed_currencies and currency not in allowed_currencies:
                    issues.append({"severity": "warning", "code": "currency_not_in_allowlist", "row_number": row_number, "field": "currency", "message": f"Currency '{currency}' is not in the configured allowlist"})
        return issues

    @staticmethod
    def _duplicate_issues(records: List[Any], unique_fields: Sequence[str]) -> List[Dict[str, Any]]:
        seen: Dict[Tuple[str, ...], int] = {}
        issues: List[Dict[str, Any]] = []
        for row_number, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                continue
            key = tuple(str(record.get(field, "") or "") for field in unique_fields)
            if all(not part for part in key):
                continue
            if key in seen:
                issues.append({"severity": "error", "code": "duplicate_key", "row_number": row_number, "first_row_number": seen[key], "fields": list(unique_fields), "key": list(key), "message": "Duplicate canonical key"})
            else:
                seen[key] = row_number
        return issues

    @staticmethod
    def _master_data_issues(records: List[Any], master_data: Mapping[str, Any]) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        lookups = {field: {str(item) for item in values} for field, values in master_data.items() if isinstance(values, list)}
        for row_number, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                continue
            for field, allowed in lookups.items():
                value = record.get(field)
                if not is_missing(value) and str(value) not in allowed:
                    issues.append({"severity": "error", "code": "orphan_dimension", "row_number": row_number, "field": field, "value": value, "message": f"'{value}' does not exist in governed master data for {field}"})
        return issues

    @staticmethod
    def _journal_balance_issues(records: List[Any], data: Mapping[str, Any], tolerance: Decimal) -> List[Dict[str, Any]]:
        if data.get("check_journal_balance", True) is False:
            return []
        group_by = data.get("journal_group_by") or ["entity_id", "period", "source_record_id", "currency"]
        groups: Dict[Tuple[str, ...], Decimal] = defaultdict(lambda: Decimal("0"))
        row_counts: Dict[Tuple[str, ...], int] = defaultdict(int)
        for record in records:
            if not isinstance(record, dict) or record.get("record_type") not in (None, "", "gl_entry") or is_missing(record.get("amount")):
                continue
            key = tuple(str(record.get(field, "") or "") for field in group_by)
            if len(key) > 2 and not key[2]:
                continue
            try:
                groups[key] += to_decimal(record["amount"], "amount")
                row_counts[key] += 1
            except ValueError:
                continue
        return [
            {"severity": "error", "code": "journal_unbalanced", "group_by": list(group_by), "group": list(key), "row_count": row_counts[key], "balance": money_str(balance), "tolerance": money_str(tolerance), "message": "Journal group does not net to zero within tolerance"}
            for key, balance in groups.items() if abs(balance) > tolerance
        ]
