"""Distribution analytics block for insurance datasets.

Aggregations are deterministic and run entirely in-process over the supplied
dataset. The block expects normalized bordereaux-style rows but also accepts
common raw aliases for GWP, channel, producer, commission, and period fields.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple

from app.core.universal_base import UniversalBlock


_ALIASES = {
    "premium": ("premium", "gwp", "gross_written_premium", "gross written premium", "written_premium"),
    "commission": ("commission", "commission_amount", "commission paid", "commission_paid"),
    "producer_code": ("producer_code", "producer", "producer code", "broker_code", "agent_code"),
    "channel": ("channel", "distribution_channel", "distribution channel", "producer_channel"),
    "period": ("period", "reporting_period", "reporting period", "month"),
    "policy_no": ("policy_no", "policy_number", "policy number", "policy", "policyno"),
    "expiring_premium": ("expiring_premium", "expiring premium", "prior_premium"),
    "renewal_premium": ("renewal_premium", "renewal premium", "renewed_premium"),
    "renewed": ("renewed", "is_renewed", "retained", "renewal_bound"),
}
_ALIAS_TO_FIELD = {
    re.sub(r"[\s_\-#]+", "", alias).lower(): field
    for field, aliases in _ALIASES.items()
    for alias in aliases
}
_DEFAULT_BENCHMARKS = {
    "commission_ratio": 0.12,
    "retention_proxy": 0.85,
    "average_gwp_per_producer": 100000.0,
}


class DistributionAnalyticsBlock(UniversalBlock):
    """Summarize, benchmark, and trend insurance distribution performance."""

    name = "distribution_analytics"
    version = "1.0.0"
    description = "Deterministic insurance distribution analytics from input datasets"
    layer = 3
    tags = ["insurance", "distribution", "analytics", "bordereaux"]
    requires: List[str] = []
    default_config = {"benchmarks": _DEFAULT_BENCHMARKS}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": "Normalized bordereaux records or raw CSV/JSON dataset",
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [{"name": "metrics", "type": "json", "label": "Metrics"}],
        },
        "params": [
            {
                "name": "action",
                "type": "select",
                "label": "Action",
                "options": ["summary", "benchmark", "trend"],
                "default": "summary",
            }
        ],
        "quick_actions": [],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Dispatch distribution analytics operations."""
        params = params or {}
        action = params.get("action")
        if action is None and isinstance(input_data, dict):
            action = input_data.get("action")
        action = action or "summary"

        records, errors = self._prepare_records(input_data)
        if action == "summary":
            return self._summary(records, errors)
        if action == "benchmark":
            return self._benchmark(records, errors, input_data, params)
        if action == "trend":
            return self._trend(records, errors)
        return {
            "status": "error",
            "error": f"Unknown action: {action}",
            "supported_actions": ["summary", "benchmark", "trend"],
        }

    def _summary(self, records: List[Dict[str, Any]], errors: List[Dict[str, Any]]) -> Dict:
        metrics = self._summary_metrics(records)
        return {
            "status": "success" if records else "error",
            "action": "summary",
            "record_count": len(records),
            "skipped_count": len(errors),
            "validation_errors": errors,
            "metrics": metrics,
        }

    def _benchmark(self, records: List[Dict[str, Any]], errors: List[Dict[str, Any]], input_data: Any, params: Dict) -> Dict:
        metrics = self._summary_metrics(records)
        benchmarks = dict(self.default_config["benchmarks"])
        supplied = params.get("benchmarks") or self._payload_value(input_data, "benchmarks") or {}
        if isinstance(supplied, dict):
            benchmarks.update(supplied)

        productivity = metrics["producer_productivity"]
        actuals = {
            "commission_ratio": metrics["commission_ratio"],
            "retention_proxy": metrics["retention_proxy"]["value"],
            "average_gwp_per_producer": productivity["average_gwp_per_producer"],
        }
        comparisons = {}
        for metric_name, actual in actuals.items():
            target = benchmarks.get(metric_name)
            comparisons[metric_name] = {
                "actual": actual,
                "benchmark": target,
                "delta": self._round(actual - target) if actual is not None and target is not None else None,
                "meets_benchmark": actual >= target if actual is not None and target is not None else None,
            }

        return {
            "status": "success" if records else "error",
            "action": "benchmark",
            "record_count": len(records),
            "skipped_count": len(errors),
            "validation_errors": errors,
            "metrics": metrics,
            "benchmarks": benchmarks,
            "comparisons": comparisons,
        }

    def _trend(self, records: List[Dict[str, Any]], errors: List[Dict[str, Any]]) -> Dict:
        by_period: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for record in records:
            by_period[record["period"]].append(record)

        series = []
        for period in sorted(by_period):
            period_records = by_period[period]
            metrics = self._summary_metrics(period_records)
            series.append(
                {
                    "period": period,
                    "gwp": metrics["total_gwp"],
                    "policy_count": metrics["policy_count"],
                    "producer_count": metrics["producer_productivity"]["producer_count"],
                    "commission_ratio": metrics["commission_ratio"],
                    "retention_proxy": metrics["retention_proxy"]["value"],
                }
            )

        first = series[0] if series else {}
        last = series[-1] if series else {}
        gwp_change = self._round((last.get("gwp") or 0.0) - (first.get("gwp") or 0.0)) if series else None
        ratio_change = self._delta(last.get("commission_ratio"), first.get("commission_ratio")) if series else None
        retention_change = self._delta(last.get("retention_proxy"), first.get("retention_proxy")) if series else None

        return {
            "status": "success" if records else "error",
            "action": "trend",
            "record_count": len(records),
            "skipped_count": len(errors),
            "validation_errors": errors,
            "series": series,
            "trend": {
                "period_count": len(series),
                "gwp_change": gwp_change,
                "gwp_direction": self._direction(gwp_change),
                "commission_ratio_change": ratio_change,
                "retention_proxy_change": retention_change,
            },
        }

    def _summary_metrics(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_gwp = self._round(sum(record["premium"] for record in records))
        total_commission = self._round(sum(record.get("commission", 0.0) for record in records))

        gwp_by_channel: Dict[str, float] = defaultdict(float)
        by_producer: Dict[str, Dict[str, Any]] = {}
        policies = set()
        for record in records:
            channel = record.get("channel") or "unknown"
            gwp_by_channel[channel] += record["premium"]
            producer = record.get("producer_code") or "UNKNOWN"
            policies.add(record.get("policy_no"))
            if producer not in by_producer:
                by_producer[producer] = {"producer_code": producer, "gwp": 0.0, "policy_count": 0}
            by_producer[producer]["gwp"] += record["premium"]
            by_producer[producer]["policy_count"] += 1

        producer_rows = []
        for producer in sorted(by_producer):
            item = by_producer[producer]
            item["gwp"] = self._round(item["gwp"])
            item["avg_gwp_per_policy"] = self._round(item["gwp"] / item["policy_count"]) if item["policy_count"] else 0.0
            producer_rows.append(item)
        producer_rows.sort(key=lambda item: (-item["gwp"], item["producer_code"]))

        producer_count = len(by_producer)
        retention = self._retention_proxy(records)
        return {
            "total_gwp": total_gwp,
            "policy_count": len([policy for policy in policies if policy]),
            "gwp_by_channel": {key: self._round(gwp_by_channel[key]) for key in sorted(gwp_by_channel)},
            "commission_total": total_commission,
            "commission_ratio": self._round(total_commission / total_gwp) if total_gwp else None,
            "producer_productivity": {
                "producer_count": producer_count,
                "average_gwp_per_producer": self._round(total_gwp / producer_count) if producer_count else 0.0,
                "by_producer": producer_rows,
            },
            "retention_proxy": retention,
        }

    def _retention_proxy(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        expiring = sum(record.get("expiring_premium", 0.0) for record in records)
        renewal = sum(record.get("renewal_premium", 0.0) for record in records)
        if expiring > 0:
            return {"value": self._round(renewal / expiring), "basis": "renewal_premium_over_expiring_premium"}

        flagged = [record for record in records if record.get("renewed") is not None]
        if flagged:
            retained = sum(1 for record in flagged if record.get("renewed") is True)
            return {"value": self._round(retained / len(flagged)), "basis": "renewed_flag_ratio"}

        periods = sorted({record["period"] for record in records})
        if len(periods) > 1:
            first_period = periods[0]
            first_policies = {record["policy_no"] for record in records if record["period"] == first_period and record.get("policy_no")}
            later_policies = {record["policy_no"] for record in records if record["period"] != first_period and record.get("policy_no")}
            if first_policies:
                return {
                    "value": self._round(len(first_policies & later_policies) / len(first_policies)),
                    "basis": "policy_reappearance_after_first_period",
                }

        return {"value": None, "basis": "insufficient_retention_fields"}

    def _prepare_records(self, input_data: Any) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        rows, parse_errors = self._extract_rows(input_data)
        records: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = list(parse_errors)
        for index, row in enumerate(rows, start=1):
            record, row_errors = self._normalize_row(row, index)
            if row_errors:
                errors.extend(row_errors)
            elif record is not None:
                records.append(record)
        return records, errors

    def _extract_rows(self, input_data: Any) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        payload = self._extract_payload(input_data)
        if isinstance(payload, list):
            rows = []
            errors = []
            for index, item in enumerate(payload, start=1):
                if isinstance(item, dict):
                    rows.append(item)
                else:
                    errors.append(self._error(index, "row", "Each dataset row must be an object", item))
            return rows, errors
        if isinstance(payload, dict):
            if self._looks_like_row(payload):
                return [payload], []
            for key in ("normalized_records", "records", "rows", "data", "dataset", "bordereaux"):
                if key in payload:
                    return self._extract_rows(payload[key])
            return [], [self._error(0, "input", "Dataset object must contain rows or analytics fields", payload)]
        if isinstance(payload, str):
            text = payload.strip()
            if not text:
                return [], [self._error(0, "input", "Empty dataset payload", payload)]
            if text[0] in "[{":
                try:
                    return self._extract_rows(json.loads(text))
                except json.JSONDecodeError as exc:
                    return [], [self._error(0, "input", f"Invalid JSON payload: {exc}", None)]
            return self._parse_csv(text)
        return [], [self._error(0, "input", f"Unsupported dataset type: {type(payload).__name__}", None)]

    def _extract_payload(self, input_data: Any) -> Any:
        if isinstance(input_data, dict) and "normalized_records" in input_data:
            return input_data["normalized_records"]
        return input_data

    def _parse_csv(self, text: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        try:
            reader = csv.DictReader(StringIO(text))
            if not reader.fieldnames:
                return [], [self._error(0, "input", "CSV header row is required", None)]
            return [dict(row) for row in reader], []
        except csv.Error as exc:
            return [], [self._error(0, "input", f"Invalid CSV payload: {exc}", None)]

    def _normalize_row(self, row: Dict[str, Any], index: int) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        canonical = self._canonicalize(row)
        errors = []
        for field in ("premium", "producer_code", "channel", "period"):
            if self._is_blank(canonical.get(field)):
                errors.append(self._error(index, field, "Required analytics field is missing", canonical.get(field)))

        premium = self._money(canonical.get("premium"))
        if premium is None and not self._is_blank(canonical.get("premium")):
            errors.append(self._error(index, "premium", "Premium/GWP must be numeric", canonical.get("premium")))
        period = self._normalize_period(canonical.get("period"))
        if period is None and not self._is_blank(canonical.get("period")):
            errors.append(self._error(index, "period", "Period must be YYYY-MM, YYYY-MM-DD, or MM/YYYY", canonical.get("period")))

        if errors:
            return None, errors

        record = {
            "premium": premium or 0.0,
            "producer_code": str(canonical.get("producer_code")).strip().upper(),
            "channel": str(canonical.get("channel") or "unknown").strip().lower(),
            "period": period,
            "policy_no": str(canonical.get("policy_no") or f"row-{index}").strip(),
        }
        for field in ("commission", "expiring_premium", "renewal_premium"):
            if not self._is_blank(canonical.get(field)):
                value = self._money(canonical.get(field))
                if value is not None:
                    record[field] = value
        if not self._is_blank(canonical.get("renewed")):
            record["renewed"] = self._to_bool(canonical.get("renewed"))
        return record, []

    def _canonicalize(self, row: Dict[str, Any]) -> Dict[str, Any]:
        canonical: Dict[str, Any] = {}
        for key, value in row.items():
            norm_key = re.sub(r"[\s_\-#]+", "", str(key)).lower()
            field = _ALIAS_TO_FIELD.get(norm_key)
            if field and field not in canonical:
                canonical[field] = value
        return canonical

    def _looks_like_row(self, row: Dict[str, Any]) -> bool:
        canonical = self._canonicalize(row)
        return any(field in canonical for field in ("premium", "producer_code", "channel", "period"))

    def _payload_value(self, input_data: Any, key: str) -> Any:
        if isinstance(input_data, dict):
            return input_data.get(key)
        return None

    def _money(self, value: Any) -> Optional[float]:
        if self._is_blank(value) or isinstance(value, bool):
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

    def _round(self, value: float) -> float:
        return round(float(value), 4)

    def _delta(self, last: Optional[float], first: Optional[float]) -> Optional[float]:
        if last is None or first is None:
            return None
        return self._round(last - first)

    def _direction(self, value: Optional[float]) -> str:
        if value is None or value == 0:
            return "flat"
        return "up" if value > 0 else "down"

    def _is_blank(self, value: Any) -> bool:
        return value is None or (isinstance(value, str) and not value.strip())

    def _error(self, row: int, field: str, message: str, value: Any) -> Dict[str, Any]:
        return {"row": row, "field": field, "message": message, "value": value}
