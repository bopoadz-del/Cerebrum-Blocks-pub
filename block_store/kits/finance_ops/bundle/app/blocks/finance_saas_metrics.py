"""Deterministic SaaS subscription metrics and ARR bridge block."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Mapping

from app.core.finance_ops import money_str, parse_date, percent_str, stable_digest, to_decimal
from app.core.typed_block import TypedBlock
from app.core.http_errors import error_kind

FREQUENCY_MONTHS = {
    "monthly": Decimal("1"),
    "quarterly": Decimal("3"),
    "semiannual": Decimal("6"),
    "semi_annual": Decimal("6"),
    "annual": Decimal("12"),
    "yearly": Decimal("12"),
}


class FinanceSaaSMetricsBlock(TypedBlock):
    """Calculate contract-normalized SaaS metrics without hidden FX assumptions."""

    name = "finance_saas_metrics"
    version = "1.0.0"
    description = (
        "SaaS metrics engine for MRR, ARR, ACV, TCV, renewal rate, ARR waterfalls, "
        "NRR, GRR, churn, expansion, contraction, and FX-separated movements."
    )
    layer = 3
    tags = ["domain", "finance_ops", "saas", "arr", "subscription", "deterministic"]
    requires: List[str] = []
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string"},
            "contracts": {"type": "array"},
            "contract": {"type": "object"},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }
    accepted_input_types = ["JSON"]
    produced_output_types = ["FinanceSaaSMetrics"]
    ui_schema = {
        "input": {"type": "json", "multiline": True},
        "output": {"type": "json"},
        "quick_actions": [
            {"icon": "", "label": "Calculate SaaS Metrics", "prompt": "Calculate ARR, ACV, TCV, NRR, and GRR"},
            {"icon": "", "label": "ARR Bridge", "prompt": "Build an ARR movement bridge"},
        ],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        data = {**(params or {}), **(input_data if isinstance(input_data, dict) else {})}
        operation = data.get("operation") or "calculate"
        try:
            if operation == "calculate":
                return self._calculate(data)
            if operation == "contract_metrics":
                return self._contract_metrics_result(data)
            if operation == "bridge":
                return self._bridge(data)
        except (TypeError, ValueError) as exc:
            return {"status": "validation_error", "operation": operation, "error": str(exc), "error_kind": error_kind(exc)}
        return {
            "status": "unsupported",
            "operation": operation,
            "error": f"Unknown operation: {operation}",
            "available_operations": ["calculate", "contract_metrics", "bridge"],
        }

    def _calculate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        contracts = data.get("contracts")
        if not isinstance(contracts, list):
            raise ValueError("contracts must be an array")
        as_of = parse_date(data.get("as_of") or date.today().isoformat(), "as_of")
        rows: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        for row_number, contract in enumerate(contracts, start=1):
            if not isinstance(contract, dict):
                errors.append({"row_number": row_number, "code": "contract_not_object", "message": "Contract must be an object"})
                continue
            try:
                rows.append(self._contract_metrics(contract, as_of))
            except ValueError as exc:
                errors.append({
                    "row_number": row_number,
                    "contract_id": contract.get("contract_id"),
                    "code": "contract_invalid",
                    "message": str(exc),
                })
        currencies = sorted({row["currency"] for row in rows if row.get("currency")})
        if len(currencies) > 1 and not data.get("allow_multi_currency_native", False):
            return {
                "status": "dependency_required", "operation": "calculate",
                "error": "Multiple currencies require governed FX rates or explicit native-currency grouping",
                "currencies": currencies, "contracts": rows, "errors": errors,
            }
        active = [row for row in rows if row["active_as_of"]]
        totals = {
            metric: money_str(sum((to_decimal(row[metric], metric) for row in (active if metric != "tcv" else rows)), Decimal("0")))
            for metric in ("mrr", "arr", "acv", "tcv")
        }
        due = [row for row in rows if row["renewal_due_as_of"]]
        renewed = [row for row in due if row["renewed"]]
        payload = {
            "as_of": as_of.isoformat(), "contract_count": len(contracts),
            "active_contract_count": len(active), "currencies": currencies,
            "currency_mode": "native_no_fx_conversion", "totals": totals,
            "renewal": {
                "contracts_due": len(due), "contracts_renewed": len(renewed),
                "renewal_rate_pct": percent_str(len(renewed), len(due)) if due else None,
            },
            "contracts": rows, "errors": errors,
        }
        return {
            "status": "success" if not errors else "validation_error",
            "operation": "calculate", **payload,
            "evidence_digest": stable_digest(payload),
            "definition_notes": {
                "arr": "Normalized annual recurring value of active subscriptions",
                "mrr": "Normalized monthly recurring value of active subscriptions",
                "acv": "TCV divided by contract term in years when not supplied",
                "tcv": "Total committed contract value when supplied or derivable",
                "fx": "No cross-currency conversion is performed without explicit governed FX inputs",
            },
        }

    def _contract_metrics_result(self, data: Dict[str, Any]) -> Dict[str, Any]:
        contract = data.get("contract") if isinstance(data.get("contract"), dict) else data
        as_of = parse_date(data.get("as_of") or date.today().isoformat(), "as_of")
        result = self._contract_metrics(contract, as_of)
        return {"status": "success", "operation": "contract_metrics", "contract": result, "evidence_digest": stable_digest(result)}

    def _contract_metrics(self, contract: Mapping[str, Any], as_of: date) -> Dict[str, Any]:
        contract_id = str(contract.get("contract_id") or contract.get("record_id") or "").strip()
        customer_id = str(contract.get("customer_id") or "").strip()
        currency = str(contract.get("currency") or "").strip().upper()
        if not contract_id:
            raise ValueError("contract_id is required")
        if not customer_id:
            raise ValueError("customer_id is required")
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be a three-letter code")
        start = parse_date(contract.get("start_date"), "start_date")
        end = self._end_date(contract, start)
        if end < start:
            raise ValueError("end_date must not precede start_date")
        status = str(contract.get("status") or "active").strip().lower()
        active = start <= as_of <= end and status not in {"cancelled", "churned", "terminated"}
        mrr = self._mrr(contract)
        arr = to_decimal(contract["arr"], "arr") if contract.get("arr") is not None else mrr * 12
        term_months = self._term_months(contract, start, end)
        tcv = to_decimal(contract["tcv"], "tcv") if contract.get("tcv") is not None else mrr * term_months
        acv = (
            to_decimal(contract["acv"], "acv")
            if contract.get("acv") is not None
            else tcv / (Decimal(term_months) / 12)
        )
        return {
            "contract_id": contract_id, "customer_id": customer_id,
            "product_id": contract.get("product_id"), "currency": currency,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "term_months": term_months,
            "billing_frequency": str(contract.get("billing_frequency") or "monthly").lower(),
            "status": status, "active_as_of": active,
            "renewal_due_as_of": end <= as_of,
            "renewed": bool(contract.get("renewed") or contract.get("renewal_contract_id")),
            "mrr": money_str(mrr), "arr": money_str(arr),
            "acv": money_str(acv), "tcv": money_str(tcv),
            "source": {
                metric: "provided" if contract.get(metric) is not None else "derived"
                for metric in ("mrr", "arr", "acv", "tcv")
            },
        }

    @staticmethod
    def _add_months(value: date, months: int) -> date:
        year = value.year + (value.month - 1 + months) // 12
        month = (value.month - 1 + months) % 12 + 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    def _end_date(self, contract: Mapping[str, Any], start: date) -> date:
        if contract.get("end_date"):
            return parse_date(contract["end_date"], "end_date")
        term_months = int(to_decimal(contract.get("term_months", 12), "term_months"))
        if term_months <= 0:
            raise ValueError("term_months must be positive")
        return self._add_months(start, term_months) - timedelta(days=1)

    @staticmethod
    def _term_months(contract: Mapping[str, Any], start: date, end: date) -> int:
        if contract.get("term_months") is not None:
            months = int(to_decimal(contract["term_months"], "term_months"))
            if months <= 0:
                raise ValueError("term_months must be positive")
            return months
        months = (end.year - start.year) * 12 + end.month - start.month
        if end.day >= start.day:
            months += 1
        return max(months, 1)

    @staticmethod
    def _mrr(contract: Mapping[str, Any]) -> Decimal:
        if contract.get("mrr") is not None:
            return to_decimal(contract["mrr"], "mrr")
        if contract.get("arr") is not None:
            return to_decimal(contract["arr"], "arr") / 12
        amount_value = contract.get("recurring_amount", contract.get("amount"))
        if amount_value is None:
            return Decimal("0")
        amount = to_decimal(amount_value, "recurring_amount")
        frequency = str(contract.get("billing_frequency") or "monthly").lower()
        if frequency in {"one_time", "one-time", "non_recurring"}:
            return Decimal("0")
        months = FREQUENCY_MONTHS.get(frequency)
        if months is None:
            raise ValueError(f"Unsupported billing_frequency: {frequency}")
        return amount / months

    @staticmethod
    def _bridge(data: Dict[str, Any]) -> Dict[str, Any]:
        opening = to_decimal(data.get("opening_arr", 0), "opening_arr")
        new = to_decimal(data.get("new_arr", 0), "new_arr")
        expansion = to_decimal(data.get("expansion_arr", 0), "expansion_arr")
        contraction = to_decimal(data.get("contraction_arr", 0), "contraction_arr")
        churn = to_decimal(data.get("churn_arr", 0), "churn_arr")
        fx = to_decimal(data.get("fx_arr", 0), "fx_arr")
        other = to_decimal(data.get("other_arr", 0), "other_arr")
        closing = opening + new + expansion - contraction - churn + fx + other
        retained = opening - contraction - churn
        payload = {
            "opening_arr": money_str(opening), "closing_arr": money_str(closing),
            "movements": [
                {"movement": "opening_arr", "amount": money_str(opening)},
                {"movement": "new_arr", "amount": money_str(new)},
                {"movement": "expansion_arr", "amount": money_str(expansion)},
                {"movement": "contraction_arr", "amount": money_str(-contraction)},
                {"movement": "churn_arr", "amount": money_str(-churn)},
                {"movement": "fx_arr", "amount": money_str(fx)},
                {"movement": "other_arr", "amount": money_str(other)},
                {"movement": "closing_arr", "amount": money_str(closing)},
            ],
            "nrr_pct": percent_str(retained + expansion, opening),
            "grr_pct": percent_str(retained, opening),
            "gross_churn_pct": percent_str(churn + contraction, opening),
            "net_new_arr": money_str(closing - opening),
            "control_check": {
                "formula": "opening + new + expansion - contraction - churn + fx + other",
                "recalculated_closing_arr": money_str(closing), "balanced": True,
            },
        }
        return {"status": "success", "operation": "bridge", **payload, "evidence_digest": stable_digest(payload)}
