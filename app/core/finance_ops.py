"""Shared deterministic primitives for Cerebrum FinanceOps blocks.

Money is represented internally with :class:`decimal.Decimal` and serialized as
fixed-point strings. The module contains no network, filesystem, or database
side effects so Store blocks remain portable and auditable.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

MONEY_QUANT = Decimal("0.0001")
DISPLAY_QUANT = Decimal("0.01")
RATE_QUANT = Decimal("0.000001")
DEFAULT_TOLERANCE = Decimal("0.01")

CANONICAL_DIMENSIONS: Tuple[str, ...] = (
    "entity_id",
    "business_unit_id",
    "product_id",
    "industry_id",
    "geography_id",
    "function_id",
    "department_id",
    "cost_center_id",
    "project_id",
    "customer_id",
    "contract_id",
    "employee_id",
    "vendor_id",
    "account_id",
    "currency",
    "period",
    "scenario",
    "version",
)

CANONICAL_FACT_TYPES: Dict[str, Tuple[str, ...]] = {
    "gl_entry": ("record_id", "entity_id", "account_id", "period", "currency", "amount"),
    "subscription_contract": ("record_id", "customer_id", "contract_id", "start_date", "currency"),
    "workforce_record": ("record_id", "employee_id", "entity_id", "period", "currency"),
    "budget_line": ("record_id", "entity_id", "account_id", "period", "currency", "amount", "scenario", "version"),
    "forecast_line": ("record_id", "entity_id", "account_id", "period", "currency", "amount", "scenario", "version"),
    "project_cost": ("record_id", "project_id", "entity_id", "period", "currency", "amount"),
}

CANONICAL_FIELDS: Tuple[str, ...] = (
    "record_type", "record_id", "source_system", "source_record_id",
    "source_row_number", "transaction_date", "start_date", "end_date", "status",
    *CANONICAL_DIMENSIONS,
    "amount", "quantity", "debit", "credit", "mrr", "arr", "acv", "tcv",
    "term_months", "billing_frequency", "metadata",
)

FIELD_ALIASES: Dict[str, str] = {
    "id": "record_id", "line_id": "record_id", "row_id": "record_id",
    "voucher": "source_record_id", "voucher_id": "source_record_id",
    "journal_id": "source_record_id", "document_number": "source_record_id",
    "legal_entity": "entity_id", "entity": "entity_id",
    "business_unit": "business_unit_id", "bu": "business_unit_id",
    "product": "product_id", "industry": "industry_id",
    "region": "geography_id", "geography": "geography_id",
    "function": "function_id", "department": "department_id",
    "cost_centre": "cost_center_id", "cost_center": "cost_center_id",
    "project": "project_id", "customer": "customer_id", "contract": "contract_id",
    "employee": "employee_id", "vendor": "vendor_id", "account": "account_id",
    "gl_account": "account_id", "account_code": "account_id",
    "posting_date": "transaction_date", "date": "transaction_date",
    "fiscal_period": "period", "month": "period", "currency_code": "currency",
    "value": "amount", "net_amount": "amount", "budget_version": "version",
    "forecast_version": "version",
}


def normalize_key(value: Any) -> str:
    """Normalize a source heading or identifier to snake_case."""
    text = str(value or "").strip()
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    return text.strip("_").lower()


def canonical_field(value: Any) -> str:
    key = normalize_key(value)
    return FIELD_ALIASES.get(key, key)


def to_decimal(value: Any, field_name: str = "value") -> Decimal:
    """Convert a value without binary-float contamination."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        raise ValueError(f"{field_name} is required")
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")
    if isinstance(value, float):
        value = str(value)
    text = str(value).strip().replace(",", "")
    if not text:
        raise ValueError(f"{field_name} is empty")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} is not a valid decimal: {value!r}") from exc


def quantize_money(value: Any) -> Decimal:
    return to_decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def money_str(value: Any) -> str:
    return format(quantize_money(value), "f")


def display_money_str(value: Any) -> str:
    return format(to_decimal(value).quantize(DISPLAY_QUANT, rounding=ROUND_HALF_UP), "f")


def rate_str(value: Any) -> str:
    return format(to_decimal(value).quantize(RATE_QUANT, rounding=ROUND_HALF_UP), "f")


def percent_str(numerator: Any, denominator: Any) -> Optional[str]:
    den = to_decimal(denominator, "denominator")
    if den == 0:
        return None
    pct = (to_decimal(numerator, "numerator") / den) * Decimal("100")
    return format(pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def parse_date(value: Any, field_name: str = "date") -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO YYYY-MM-DD") from exc


def canonical_period(value: Any) -> str:
    """Return a governed YYYY-MM period from date/period input."""
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m")
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}", text):
        month = int(text[-2:])
        if 1 <= month <= 12:
            return text
    if re.fullmatch(r"\d{6}", text):
        month = int(text[-2:])
        if 1 <= month <= 12:
            return f"{text[:4]}-{text[4:]}"
    try:
        return parse_date(text, "period").strftime("%Y-%m")
    except ValueError as exc:
        raise ValueError("period must be YYYY-MM, YYYYMM, or an ISO date") from exc


def stable_digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def normalize_record_keys(record: Mapping[str, Any], field_map: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Apply explicit mapping first, then standard aliases."""
    explicit = {normalize_key(k): canonical_field(v) for k, v in (field_map or {}).items()}
    normalized: Dict[str, Any] = {}
    for raw_key, value in record.items():
        key = normalize_key(raw_key)
        target = explicit.get(key) or canonical_field(key)
        normalized[target] = value
    return normalized


def normalize_common_values(record: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(record)
    if not is_missing(out.get("period")):
        out["period"] = canonical_period(out["period"])
    elif not is_missing(out.get("transaction_date")):
        out["period"] = canonical_period(out["transaction_date"])
    if not is_missing(out.get("currency")):
        out["currency"] = str(out["currency"]).strip().upper()
    for field in ("amount", "debit", "credit", "mrr", "arr", "acv", "tcv"):
        if field in out and not is_missing(out[field]):
            out[field] = money_str(out[field])
    if "term_months" in out and not is_missing(out["term_months"]):
        out["term_months"] = int(to_decimal(out["term_months"], "term_months"))
    for field in ("transaction_date", "start_date", "end_date"):
        if field in out and not is_missing(out[field]):
            out[field] = parse_date(out[field], field).isoformat()
    return out


def validate_canonical_record(record_type: str, record: Mapping[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    required = CANONICAL_FACT_TYPES.get(record_type)
    if required is None:
        return [{"severity": "error", "code": "unsupported_record_type", "field": "record_type", "message": f"Unsupported record_type: {record_type}"}]
    for field in required:
        if is_missing(record.get(field)):
            issues.append({"severity": "error", "code": "required_field_missing", "field": field, "message": f"Required field '{field}' is missing"})
    if not is_missing(record.get("currency")):
        currency = str(record["currency"]).upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            issues.append({"severity": "error", "code": "invalid_currency", "field": "currency", "message": "currency must be a three-letter ISO-style code"})
    if not is_missing(record.get("period")):
        try:
            canonical_period(record["period"])
        except ValueError as exc:
            issues.append({"severity": "error", "code": "invalid_period", "field": "period", "message": str(exc)})
    if not is_missing(record.get("amount")):
        try:
            to_decimal(record["amount"], "amount")
        except ValueError as exc:
            issues.append({"severity": "error", "code": "invalid_amount", "field": "amount", "message": str(exc)})
    return issues


def group_decimal_sum(records: Iterable[Mapping[str, Any]], group_by: Sequence[str], amount_field: str) -> Dict[Tuple[str, ...], Decimal]:
    totals: Dict[Tuple[str, ...], Decimal] = {}
    for record in records:
        key = tuple(str(record.get(field, "") or "") for field in group_by)
        amount = to_decimal(record.get(amount_field, 0), amount_field)
        totals[key] = totals.get(key, Decimal("0")) + amount
    return totals
