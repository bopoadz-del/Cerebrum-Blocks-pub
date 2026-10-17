"""Bordereaux ingest block for simulated insurance carrier feeds.

The block accepts CSV or JSON-like rows from a simulated carrier feed and
normalizes the common bordereaux fields used by downstream insurance blocks.
It intentionally performs no network calls and does not integrate with live
carrier APIs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple

from app.core.universal_base import UniversalBlock


_FIELD_ALIASES = {
    "premium": (
        "premium",
        "gwp",
        "gross_written_premium",
        "gross written premium",
        "written_premium",
        "written premium",
    ),
    "policy_no": (
        "policy_no",
        "policy_number",
        "policy number",
        "policy",
        "policyno",
        "policy #",
    ),
    "producer_code": (
        "producer_code",
        "producer code",
        "producer",
        "broker_code",
        "broker code",
        "agent_code",
        "agent code",
    ),
    "lob": (
        "lob",
        "line_of_business",
        "line of business",
        "business_line",
        "class",
    ),
    "period": (
        "period",
        "reporting_period",
        "reporting period",
        "accounting_period",
        "month",
    ),
    "channel": (
        "channel",
        "distribution_channel",
        "distribution channel",
        "producer_channel",
        "producer channel",
    ),
    "commission": (
        "commission",
        "commission_amount",
        "commission amount",
        "commission_paid",
        "commission paid",
    ),
    "expiring_premium": (
        "expiring_premium",
        "expiring premium",
        "prior_premium",
        "prior premium",
    ),
    "renewal_premium": (
        "renewal_premium",
        "renewal premium",
        "renewed_premium",
        "renewed premium",
    ),
    "renewed": (
        "renewed",
        "is_renewed",
        "renewal_bound",
        "retained",
    ),
}

_ALIAS_TO_FIELD = {
    re.sub(r"[\s_\-#]+", "", alias).lower(): field
    for field, aliases in _FIELD_ALIASES.items()
    for alias in aliases
}
_REQUIRED_FIELDS = ("premium", "policy_no", "producer_code", "lob", "period")
_OPTIONAL_MONEY_FIELDS = ("commission", "expiring_premium", "renewal_premium")


class BordereauxIngestBlock(UniversalBlock):
    """Parse, validate, and normalize simulated carrier bordereaux feeds."""

    name = "bordereaux_ingest"
    version = "1.0.0"
    description = "Parse and normalize simulated insurance bordereaux CSV/JSON rows"
    layer = 3
    tags = ["insurance", "bordereaux", "ingest", "simulated-feed"]
    requires: List[str] = []
    default_config = {"default_channel": "unknown"}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": "CSV text, JSON rows, or {'rows': [...]} bordereaux payload",
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [{"name": "normalized_records", "type": "json", "label": "Records"}],
        },
        "params": [
            {
                "name": "action",
                "type": "select",
                "label": "Action",
                "options": ["parse", "validate", "normalize", "simulate_webhook"],
                "default": "normalize",
            }
        ],
        "quick_actions": [],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Dispatch bordereaux ingest operations."""
        params = params or {}
        action = params.get("action")
        if action is None and isinstance(input_data, dict):
            action = input_data.get("action")
        action = action or "normalize"

        if action == "parse":
            return self._parse_action(input_data, params)
        if action == "validate":
            return self._validate_action(input_data, params)
        if action == "normalize":
            return self._normalize_action(input_data, params)
        if action == "simulate_webhook":
            return self._simulate_webhook(input_data, params)
        return {
            "status": "error",
            "error": f"Unknown action: {action}",
            "supported_actions": ["parse", "validate", "normalize", "simulate_webhook"],
        }

    def _parse_action(self, input_data: Any, params: Dict) -> Dict:
        rows, errors, detected_format = self._parse_rows(input_data)
        normalized, validation_errors = self._normalize_rows(rows, params)
        all_errors = errors + validation_errors
        return {
            "status": "success" if not errors else "error",
            "action": "parse",
            "detected_format": detected_format,
            "raw_records": rows,
            "normalized_records": normalized,
            "validation_errors": all_errors,
            "record_count": len(rows),
            "accepted_count": len(normalized),
            "rejected_count": max(0, len(rows) - len(normalized)),
        }

    def _validate_action(self, input_data: Any, params: Dict) -> Dict:
        rows, errors, detected_format = self._parse_rows(input_data)
        normalized, validation_errors = self._normalize_rows(rows, params)
        all_errors = errors + validation_errors
        return {
            "status": "success" if not all_errors else "error",
            "action": "validate",
            "detected_format": detected_format,
            "normalized_records": normalized,
            "validation_errors": all_errors,
            "record_count": len(rows),
            "accepted_count": len(normalized),
            "rejected_count": max(0, len(rows) - len(normalized)),
        }

    def _normalize_action(self, input_data: Any, params: Dict) -> Dict:
        rows, errors, detected_format = self._parse_rows(input_data)
        normalized, validation_errors = self._normalize_rows(rows, params)
        all_errors = errors + validation_errors
        return {
            "status": "success" if not all_errors else "error",
            "action": "normalize",
            "detected_format": detected_format,
            "normalized_records": normalized,
            "validation_errors": all_errors,
            "record_count": len(rows),
            "accepted_count": len(normalized),
            "rejected_count": max(0, len(rows) - len(normalized)),
        }

    def _simulate_webhook(self, input_data: Any, params: Dict) -> Dict:
        rows, errors, detected_format = self._parse_rows(input_data)
        normalized, validation_errors = self._normalize_rows(rows, params)
        all_errors = errors + validation_errors
        carrier = params.get("carrier") or self._payload_value(input_data, "carrier") or "simulated_carrier"
        feed_id = params.get("feed_id") or self._payload_value(input_data, "feed_id")
        if not feed_id:
            digest = hashlib.sha256(
                json.dumps(rows, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:12]
            feed_id = f"sim-{digest}"

        return {
            "status": "success" if normalized else "error",
            "action": "simulate_webhook",
            "source": "simulated_carrier_feed",
            "simulated": True,
            "external_api_calls": 0,
            "carrier": carrier,
            "feed_id": feed_id,
            "detected_format": detected_format,
            "normalized_records": normalized,
            "validation_errors": all_errors,
            "record_count": len(rows),
            "accepted_count": len(normalized),
            "rejected_count": max(0, len(rows) - len(normalized)),
        }

    def _parse_rows(self, input_data: Any) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
        payload = self._extract_payload(input_data)
        if payload is None:
            return [], [self._error(0, "input", "No bordereaux payload provided", None)], "empty"

        if isinstance(payload, list):
            rows, errors = self._list_to_rows(payload)
            return rows, errors, "json"

        if isinstance(payload, dict):
            nested = self._nested_payload(payload)
            if nested is not payload:
                return self._parse_rows(nested)
            if self._looks_like_row(payload):
                return [payload], [], "json"
            return [], [self._error(0, "input", "JSON object must contain rows/data or bordereaux fields", payload)], "json"

        if isinstance(payload, str):
            text = payload.strip()
            if not text:
                return [], [self._error(0, "input", "Empty bordereaux payload", payload)], "empty"
            if text[0] in "[{":
                try:
                    return self._parse_rows(json.loads(text))
                except json.JSONDecodeError as exc:
                    return [], [self._error(0, "input", f"Invalid JSON payload: {exc}", None)], "json"
            return self._parse_csv(text)

        return [], [self._error(0, "input", f"Unsupported payload type: {type(payload).__name__}", None)], "unknown"

    def _extract_payload(self, input_data: Any) -> Any:
        if not isinstance(input_data, dict):
            return input_data
        for key in ("rows", "records", "data", "bordereaux", "payload", "csv", "content"):
            if key in input_data:
                return input_data[key]
        return input_data

    def _nested_payload(self, payload: Dict[str, Any]) -> Any:
        for key in ("rows", "records", "data", "bordereaux", "payload", "csv", "content"):
            if key in payload:
                return payload[key]
        return payload

    def _list_to_rows(self, items: List[Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        rows: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        for index, item in enumerate(items, start=1):
            if isinstance(item, dict):
                rows.append(item)
            else:
                errors.append(self._error(index, "row", "Each bordereaux row must be an object", item))
        return rows, errors

    def _parse_csv(self, text: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
        try:
            reader = csv.DictReader(StringIO(text))
            if not reader.fieldnames:
                return [], [self._error(0, "input", "CSV header row is required", None)], "csv"
            rows = [dict(row) for row in reader]
            return rows, [], "csv"
        except csv.Error as exc:
            return [], [self._error(0, "input", f"Invalid CSV payload: {exc}", None)], "csv"

    def _normalize_rows(self, rows: List[Dict[str, Any]], params: Dict) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        normalized: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            record, row_errors = self._normalize_row(row, index, params)
            if row_errors:
                errors.extend(row_errors)
            elif record is not None:
                normalized.append(record)
        return normalized, errors

    def _normalize_row(self, row: Dict[str, Any], index: int, params: Dict) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        canonical = self._canonicalize_row(row)
        errors: List[Dict[str, Any]] = []

        for field in _REQUIRED_FIELDS:
            if self._is_blank(canonical.get(field)):
                errors.append(self._error(index, field, "Required field is missing", canonical.get(field)))

        premium = self._money(canonical.get("premium"))
        if premium is None and not self._is_blank(canonical.get("premium")):
            errors.append(self._error(index, "premium", "Premium must be a number", canonical.get("premium")))
        elif premium is not None and premium < 0:
            errors.append(self._error(index, "premium", "Premium must be non-negative", canonical.get("premium")))

        period = self._normalize_period(canonical.get("period"))
        if period is None and not self._is_blank(canonical.get("period")):
            errors.append(self._error(index, "period", "Period must be YYYY-MM, YYYY-MM-DD, or MM/YYYY", canonical.get("period")))

        optional_money: Dict[str, float] = {}
        for field in _OPTIONAL_MONEY_FIELDS:
            if self._is_blank(canonical.get(field)):
                continue
            value = self._money(canonical.get(field))
            if value is None:
                errors.append(self._error(index, field, f"{field} must be a number", canonical.get(field)))
            else:
                optional_money[field] = value

        if errors:
            return None, errors

        record = {
            "policy_no": str(canonical["policy_no"]).strip(),
            "producer_code": str(canonical["producer_code"]).strip().upper(),
            "lob": str(canonical["lob"]).strip().upper(),
            "period": period,
            "premium": premium,
            "channel": str(canonical.get("channel") or params.get("default_channel") or self.default_config["default_channel"]).strip().lower(),
        }
        for field, value in optional_money.items():
            record[field] = value
        if "renewed" in canonical and not self._is_blank(canonical.get("renewed")):
            record["renewed"] = self._to_bool(canonical.get("renewed"))
        return record, []

    def _canonicalize_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        canonical: Dict[str, Any] = {}
        for key, value in row.items():
            norm_key = re.sub(r"[\s_\-#]+", "", str(key)).lower()
            field = _ALIAS_TO_FIELD.get(norm_key)
            if field and field not in canonical:
                canonical[field] = value
        return canonical

    def _looks_like_row(self, payload: Dict[str, Any]) -> bool:
        canonical = self._canonicalize_row(payload)
        return any(field in canonical for field in _REQUIRED_FIELDS)

    def _payload_value(self, input_data: Any, key: str) -> Any:
        if isinstance(input_data, dict):
            return input_data.get(key)
        return None

    def _money(self, value: Any) -> Optional[float]:
        if self._is_blank(value):
            return None
        if isinstance(value, bool):
            return None
        text = str(value).strip().replace("$", "").replace(",", "")
        try:
            return round(float(Decimal(text)), 2)
        except (InvalidOperation, ValueError):
            return None

    def _normalize_period(self, value: Any) -> Optional[str]:
        if self._is_blank(value):
            return None
        text = str(value).strip()
        match = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-\d{1,2})?", text)
        if match:
            year, month = int(match.group(1)), int(match.group(2))
            if 1 <= month <= 12:
                return f"{year:04d}-{month:02d}"
            return None
        match = re.fullmatch(r"(\d{1,2})[/-](\d{4})", text)
        if match:
            month, year = int(match.group(1)), int(match.group(2))
            if 1 <= month <= 12:
                return f"{year:04d}-{month:02d}"
        return None

    def _to_bool(self, value: Any) -> Optional[bool]:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "renewed", "retained", "bound"}:
            return True
        if text in {"0", "false", "no", "n", "lost", "not renewed"}:
            return False
        return None

    def _is_blank(self, value: Any) -> bool:
        return value is None or (isinstance(value, str) and not value.strip())

    def _error(self, row: int, field: str, message: str, value: Any) -> Dict[str, Any]:
        return {"row": row, "field": field, "message": message, "value": value}
