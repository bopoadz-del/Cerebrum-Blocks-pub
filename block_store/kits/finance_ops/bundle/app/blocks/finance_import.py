"""Normalize ERP, CRM, HCM, project-cost, budget, and forecast rows."""

from __future__ import annotations

import csv
from typing import Any, Dict, List, Mapping

from app.core.finance_ops import (
    CANONICAL_FIELDS, is_missing, money_str, normalize_common_values,
    normalize_record_keys, stable_digest, to_decimal, validate_canonical_record,
)
from app.core.typed_block import TypedBlock
from app.core.http_errors import error_kind

SOURCE_SPECS: Dict[str, Dict[str, Any]] = {
    "gl": {"record_type": "gl_entry", "field_map": {"line_id": "record_id", "voucher_id": "source_record_id", "journal_id": "source_record_id", "legal_entity": "entity_id", "gl_account": "account_id", "cost_centre": "cost_center_id", "posting_date": "transaction_date", "fiscal_period": "period", "currency_code": "currency", "net_amount": "amount"}},
    "crm_contract": {"record_type": "subscription_contract", "field_map": {"id": "record_id", "customer": "customer_id", "contract": "contract_id", "product": "product_id", "start": "start_date", "end": "end_date", "billing": "billing_frequency", "monthly_recurring_revenue": "mrr", "annual_recurring_revenue": "arr", "annual_contract_value": "acv", "total_contract_value": "tcv"}},
    "hcm_worker": {"record_type": "workforce_record", "field_map": {"id": "record_id", "worker_id": "employee_id", "legal_entity": "entity_id", "department": "department_id", "cost_centre": "cost_center_id", "base_salary": "amount", "currency_code": "currency", "fiscal_period": "period"}},
    "budget": {"record_type": "budget_line", "defaults": {"scenario": "budget"}},
    "forecast": {"record_type": "forecast_line", "defaults": {"scenario": "forecast"}},
    "project_cost": {"record_type": "project_cost"},
}


class FinanceImportBlock(TypedBlock):
    """Map tabular source rows into governed FinanceOps records."""

    name = "finance_import"
    version = "1.0.0"
    description = "Deterministic row normalizer for GL, CRM contracts, HCM workers, project costs, budgets, and forecasts."
    layer = 3
    tags = ["domain", "finance_ops", "ingestion", "normalization", "deterministic"]
    requires: List[str] = []
    input_schema = {"type": "object", "properties": {"operation": {"type": "string"}, "source_type": {"type": "string"}, "rows": {"type": "array"}, "field_map": {"type": "object"}}}
    output_schema = {"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]}
    accepted_input_types = ["JSON"]
    produced_output_types = ["FinanceImportBatch"]
    ui_schema = {"input": {"type": "json", "multiline": True}, "output": {"type": "json"}}

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        # Ingest idempotency ledger: record_id -> batch digest, plus the set
        # of already-ingested batch digests. In-instance state; a product
        # wires durable storage at the caller layer.
        self._ingested: Dict[str, str] = {}
        self._seen_batches: set = set()

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        data = {**(params or {}), **(input_data if isinstance(input_data, dict) else {})}
        operation = data.get("operation") or "normalize_rows"
        try:
            if operation == "normalize_rows":
                return self._normalize_rows(data)
            if operation == "profile":
                return self._profile(data)
            if operation == "parse_file":
                return self._parse_file(data)
            if operation == "ingest":
                return self._ingest(data)
            if operation == "reset_ingest":
                self._ingested.clear()
                self._seen_batches.clear()
                return {"status": "success", "operation": "reset_ingest"}
        except (KeyError, TypeError, ValueError) as exc:
            return {"status": "validation_error", "operation": operation, "error": str(exc), "error_kind": error_kind(exc)}
        return {"status": "unsupported", "operation": operation, "error": f"Unknown operation: {operation}", "available_operations": ["normalize_rows", "profile", "parse_file", "ingest", "reset_ingest"]}

    def _parse_file(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a CSV or XLSX file into rows, then normalize them.

        The file bytes never leave the process; openpyxl is imported lazily
        so CSV-only deployments stay light.
        """
        file_path = str(data.get("file_path") or "").strip()
        if not file_path:
            raise ValueError("file_path is required")
        from pathlib import Path

        path = Path(file_path)
        if not path.is_file():
            raise ValueError(f"file not found: {file_path}")
        suffix = path.suffix.lower()
        if suffix == ".csv":
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as fh:
                    rows = list(csv.DictReader(fh))
            except (OSError, csv.Error) as exc:
                raise ValueError(f"csv parse failed: {exc}") from exc
        elif suffix in (".xlsx", ".xlsm"):
            try:
                from openpyxl import load_workbook

                wb = load_workbook(path, read_only=True, data_only=True)
                ws = wb.active
                headers = None
                rows = []
                for row in ws.iter_rows(values_only=True):
                    values = ["" if v is None else v for v in row]
                    if headers is None:
                        headers = [str(h).strip() for h in values]
                        continue
                    record = {headers[i]: values[i] for i in range(min(len(headers), len(values)))}
                    if any(str(v).strip() for v in record.values()):
                        rows.append(record)
                wb.close()
            except (OSError, ValueError) as exc:
                raise ValueError(f"xlsx parse failed: {exc}") from exc
            except ImportError as exc:
                raise ValueError("openpyxl is required for .xlsx import") from exc
        else:
            raise ValueError(f"unsupported file type: {suffix!r} (use .csv or .xlsx)")
        if not rows:
            raise ValueError("file contains no data rows")
        return self._normalize_rows({**data, "rows": rows, "source_file": path.name})

    def _ingest(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Idempotent ingest: the same batch or the same record_id is never
        double-counted. Batch-level digest first, then per-record dedupe.
        """
        rows = data.get("rows")
        if not isinstance(rows, list) or not rows:
            raise ValueError("rows must be a non-empty array")
        batch_digest = stable_digest(rows)
        if batch_digest in self._seen_batches:
            return {
                "status": "success",
                "operation": "ingest",
                "already_ingested": True,
                "batch_digest": batch_digest,
                "accepted": 0,
                "duplicates": len(rows),
            }
        normalized = self._normalize_rows(data)
        accepted = []
        duplicates = []
        for row in normalized.get("accepted", []):
            record_id = str(row.get("record_id") or "")
            if record_id in self._ingested:
                duplicates.append(record_id)
                continue
            self._ingested[record_id] = batch_digest
            accepted.append(record_id)
        self._seen_batches.add(batch_digest)
        return {
            "status": "success",
            "operation": "ingest",
            "already_ingested": False,
            "batch_digest": batch_digest,
            "accepted": len(accepted),
            "duplicates": len(duplicates),
            "rejected": len(normalized.get("rejected", [])),
        }

    @staticmethod
    def _source_spec(data: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        source_type = str(data.get("source_type") or "").strip()
        if source_type not in SOURCE_SPECS:
            raise ValueError(f"Unsupported source_type '{source_type}'. Use: {sorted(SOURCE_SPECS)}")
        return source_type, SOURCE_SPECS[source_type]

    @staticmethod
    def _profile(data: Dict[str, Any]) -> Dict[str, Any]:
        rows = data.get("rows")
        if not isinstance(rows, list):
            raise ValueError("rows must be an array")
        columns: Dict[str, Dict[str, int]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key, value in row.items():
                item = columns.setdefault(str(key), {"present": 0, "null": 0})
                item["present"] += 1
                item["null"] += int(is_missing(value))
        return {"status": "success", "operation": "profile", "row_count": len(rows), "columns": columns, "source_digest": stable_digest(rows)}

    def _normalize_rows(self, data: Dict[str, Any]) -> Dict[str, Any]:
        rows = data.get("rows")
        if not isinstance(rows, list):
            raise ValueError("rows must be an array")
        source_type, spec = self._source_spec(data)
        source_system = str(data.get("source_system") or source_type)
        field_map = {**spec.get("field_map", {}), **(data.get("field_map") if isinstance(data.get("field_map"), dict) else {})}
        defaults = {**spec.get("defaults", {}), **(data.get("defaults") if isinstance(data.get("defaults"), dict) else {})}
        record_type = str(data.get("record_type") or spec["record_type"])
        accepted: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []
        warning_count = 0
        for row_number, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                rejected.append({"row_number": row_number, "issues": [{"severity": "error", "code": "row_not_object", "message": "Row must be an object"}]})
                continue
            normalized = {**defaults, **normalize_record_keys(row, field_map)}
            normalized.update({"record_type": record_type, "source_system": source_system, "source_row_number": row_number})
            normalized = normalize_common_values(self._derive_values(source_type, normalized))
            if is_missing(normalized.get("record_id")):
                source_id = normalized.get("source_record_id")
                normalized["record_id"] = f"{source_system}:{source_id}:{row_number}" if not is_missing(source_id) else f"{source_system}:row:{row_number}"
            known = {key: value for key, value in normalized.items() if key in CANONICAL_FIELDS}
            extras = {key: value for key, value in normalized.items() if key not in CANONICAL_FIELDS}
            metadata = dict(known.get("metadata") or {})
            if extras:
                metadata["source_fields"] = extras
            known["metadata"] = metadata
            issues = validate_canonical_record(record_type, known)
            warnings = self._warnings(source_type, known)
            warning_count += len(warnings)
            if issues:
                rejected.append({"row_number": row_number, "record": known, "issues": issues + warnings})
            else:
                accepted.append({**known, "validation_warnings": warnings})
        payload = {"source_type": source_type, "source_system": source_system, "record_type": record_type, "accepted": accepted, "rejected": rejected}
        return {
            "status": "success" if not rejected else "validation_error", "operation": "normalize_rows", **payload,
            "stats": {"input_rows": len(rows), "accepted_rows": len(accepted), "rejected_rows": len(rejected), "warning_count": warning_count},
            "batch_digest": stable_digest(payload),
        }

    @staticmethod
    def _derive_values(source_type: str, row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        if source_type == "gl" and is_missing(out.get("amount")):
            out["amount"] = money_str(to_decimal(out.get("debit", 0), "debit") - to_decimal(out.get("credit", 0), "credit"))
        if source_type == "crm_contract":
            if not is_missing(out.get("mrr")) and is_missing(out.get("arr")):
                out["arr"] = money_str(to_decimal(out["mrr"], "mrr") * 12)
            if not is_missing(out.get("arr")) and is_missing(out.get("mrr")):
                out["mrr"] = money_str(to_decimal(out["arr"], "arr") / 12)
        return out

    @staticmethod
    def _warnings(source_type: str, row: Mapping[str, Any]) -> List[Dict[str, Any]]:
        warnings: List[Dict[str, Any]] = []
        if source_type == "gl" and is_missing(row.get("source_record_id")):
            warnings.append({"severity": "warning", "code": "voucher_reference_missing", "field": "source_record_id", "message": "GL row has no voucher/journal reference"})
        if source_type == "crm_contract" and all(is_missing(row.get(field)) for field in ("mrr", "arr", "acv", "tcv")):
            warnings.append({"severity": "warning", "code": "contract_value_missing", "message": "Contract has no MRR, ARR, ACV, or TCV"})
        return warnings
