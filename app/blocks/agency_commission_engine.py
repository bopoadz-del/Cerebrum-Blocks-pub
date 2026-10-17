"""Agency Commission Engine - deterministic insurance commission math."""

import json
import os
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind


CENT = Decimal("0.01")
RATE = Decimal("0.0001")


EMBEDDED_FORMULAS: Dict[str, Any] = {
    "version": 1,
    "currency": "USD",
    "schedules": {
        "life_fyc": {
            "description": "Life first-year commission on annualized premium.",
            "line_of_business": "life",
            "transaction_type": "new_business",
            "basis": "annualized_premium",
            "effective_periods": [
                {
                    "effective_from": "2025-01-01",
                    "effective_to": None,
                    "default_level": "standard",
                    "min_rate": 0.50,
                    "max_rate": 1.20,
                    "rates": {
                        "trainee": 0.50,
                        "standard": 0.75,
                        "senior": 0.90,
                        "elite": 1.20,
                    },
                }
            ],
        },
        "pc_new": {
            "description": "Property and casualty new business commission on written premium.",
            "line_of_business": "pc",
            "transaction_type": "new_business",
            "basis": "written_premium",
            "effective_periods": [
                {
                    "effective_from": "2025-01-01",
                    "effective_to": None,
                    "default_level": "producer",
                    "min_rate": 0.08,
                    "max_rate": 0.20,
                    "rates": {
                        "csr": 0.08,
                        "producer": 0.12,
                        "senior_producer": 0.15,
                        "partner": 0.20,
                    },
                }
            ],
        },
        "renewals": {
            "description": "Renewal commission schedules by line and policy year.",
            "basis": "renewal_premium",
            "effective_periods": [
                {
                    "effective_from": "2025-01-01",
                    "effective_to": None,
                    "life": {
                        "default_rate": 0.05,
                        "min_rate": 0.03,
                        "max_rate": 0.10,
                        "year_rates": {"2": 0.10, "3": 0.075, "4+": 0.05},
                    },
                    "pc": {
                        "default_rate": 0.10,
                        "min_rate": 0.08,
                        "max_rate": 0.12,
                        "year_rates": {"2+": 0.10},
                    },
                }
            ],
        },
    },
    "overrides": {
        "description": "Upline override rates paid on the same premium basis as the sale.",
        "basis": "premium",
        "max_levels": 5,
        "hierarchy_levels": {
            "agency_manager": {"life_fyc": 0.05, "pc_new": 0.02, "renewals": 0.015},
            "regional_director": {"life_fyc": 0.025, "pc_new": 0.01, "renewals": 0.005},
            "broker_dealer": {"life_fyc": 0.01, "pc_new": 0.005, "renewals": 0.0025},
        },
    },
    "chargebacks": {
        "life_fyc": {
            "method": "free_look_full_then_pro_rata",
            "free_look_days": 30,
            "window_days": 365,
            "description": "Full chargeback in free-look period, then first-year pro rata.",
        },
        "pc_new": {
            "method": "pro_rata_term",
            "term_days": 365,
            "description": "Pro rata chargeback over the policy term.",
        },
        "renewals": {
            "method": "pro_rata_term",
            "term_days": 365,
            "description": "Pro rata chargeback over the renewal term.",
        },
    },
    "effective_dating": {
        "boundary": "inclusive",
        "date_field_precedence": ["transaction_date", "issue_date", "effective_date"],
        "default_date": "today",
    },
}


class AgencyCommissionEngineBlock(UniversalBlock):
    """Insurance agency commission calculator with effective-dated schedules."""

    name = "agency_commission_engine"
    version = "1.0.0"
    description = (
        "Deterministic agency commission engine for life FYC, P&C new business, "
        "renewals, hierarchy overrides, chargebacks, and effective dating."
    )
    layer = 3
    tags = ["domain", "insurance", "commission", "agency", "deterministic"]
    requires: List[str] = []

    default_config = {
        "formula_path_env": "AGENCY_COMMISSION_FORMULAS_PATH",
        "formula_path": "",
        "rounding": "ROUND_HALF_UP",
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": (
                '{"operation": "calculate", "product_type": "life_fyc", '
                '"premium": 10000, "agent_level": "senior"}'
            ),
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "base_commission", "type": "json", "label": "Base Commission"},
                {"name": "overrides", "type": "list", "label": "Overrides"},
                {"name": "total_commission", "type": "number", "label": "Total Commission"},
                {"name": "chargeback_amount", "type": "number", "label": "Chargeback"},
            ],
        },
        "quick_actions": [
            {"icon": "", "label": "Calculate", "prompt": "Calculate agency commission"},
            {"icon": "", "label": "Preview Overrides", "prompt": "Preview upline overrides"},
            {"icon": "", "label": "Apply Chargeback", "prompt": "Calculate commission chargeback"},
        ],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self.formulas, self.formula_source = self._load_formulas()

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**params, **data}
        operation = merged.get("operation") or merged.get("action") or "calculate"

        try:
            if operation == "calculate":
                return self._calculate(merged)
            if operation == "preview_override":
                return self._preview_override(merged)
            if operation == "apply_chargeback":
                return self._apply_chargeback(merged)
            if operation == "effective_schedule":
                return self._effective_schedule_result(merged)
        except (ValueError, TypeError) as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc), "operation": operation}

        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": [
                "calculate",
                "preview_override",
                "apply_chargeback",
                "effective_schedule",
            ],
        }

    def _load_formulas(self) -> Tuple[Dict[str, Any], str]:
        for path in self._formula_path_candidates():
            if path and path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8")), str(path)
                except (OSError, json.JSONDecodeError):
                    break
        return deepcopy(EMBEDDED_FORMULAS), "embedded"

    def _formula_path_candidates(self) -> List[Path]:
        candidates: List[Path] = []
        configured = self.config.get("formula_path") or ""
        if configured:
            candidates.append(Path(configured))

        env_key = self.config.get("formula_path_env", "AGENCY_COMMISSION_FORMULAS_PATH")
        env_path = os.environ.get(env_key, "") if env_key else ""
        if env_path:
            candidates.append(Path(env_path))

        here = Path(__file__).resolve()
        # Installed kit layout: app/blocks/<block>.py with app/data next to app/blocks.
        candidates.append(here.parents[1] / "data" / "commission_formulas.json")
        # Repository development layout: root/block_store/kits/insurance/bundle/app/data.
        if len(here.parents) > 2:
            candidates.append(
                here.parents[2]
                / "block_store"
                / "kits"
                / "insurance"
                / "bundle"
                / "app"
                / "data"
                / "commission_formulas.json"
            )
        return candidates

    def _calculate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        schedule_key, line = self._normalize_product(data)
        effective_date = self._resolve_effective_date(data)
        schedule, period = self._effective_schedule(schedule_key, effective_date)
        premium = self._premium_for_schedule(data, schedule)
        rate, rate_source = self._base_rate(data, schedule_key, line, period)

        base_amount = self._money_decimal(premium * rate)
        overrides = self._override_rows(data, schedule_key, premium)
        override_total = self._money_decimal(sum((row["_amount"] for row in overrides), Decimal("0")))
        total = self._money_decimal(base_amount + override_total)

        public_overrides = [self._public_override(row) for row in overrides]
        result = {
            "status": "success",
            "operation": "calculate",
            "formula_source": self.formula_source,
            "schedule_key": schedule_key,
            "line_of_business": line,
            "effective_date": effective_date.isoformat(),
            "premium_basis": schedule.get("basis", "premium"),
            "premium": self._money(premium),
            "base_commission": {
                "rate": self._rate(rate),
                "rate_pct": self._rate_pct(rate),
                "amount": self._money(base_amount),
                "agent_level": rate_source,
            },
            "overrides": public_overrides,
            "override_total": self._money(override_total),
            "total_commission": self._money(total),
            "currency": self._currency(data),
        }

        if data.get("cancellation_date"):
            chargeback = self._chargeback_result(data, schedule_key, total)
            result["chargeback"] = chargeback
            result["net_commission"] = self._money(
                total - self._decimal(chargeback["chargeback_amount"], "chargeback_amount")
            )
        else:
            result["net_commission"] = self._money(total)

        return result

    def _preview_override(self, data: Dict[str, Any]) -> Dict[str, Any]:
        schedule_key, line = self._normalize_product(data)
        effective_date = self._resolve_effective_date(data)
        schedule, _period = self._effective_schedule(schedule_key, effective_date)
        premium = self._premium_for_schedule(data, schedule)
        overrides = self._override_rows(data, schedule_key, premium)
        total = self._money_decimal(sum((row["_amount"] for row in overrides), Decimal("0")))

        return {
            "status": "success",
            "operation": "preview_override",
            "formula_source": self.formula_source,
            "schedule_key": schedule_key,
            "line_of_business": line,
            "effective_date": effective_date.isoformat(),
            "premium": self._money(premium),
            "overrides": [self._public_override(row) for row in overrides],
            "override_total": self._money(total),
            "currency": self._currency(data),
        }

    def _apply_chargeback(self, data: Dict[str, Any]) -> Dict[str, Any]:
        schedule_key, line = self._normalize_product(data)
        original = data.get("original_commission")
        if original is None:
            calculated = self._calculate({k: v for k, v in data.items() if k != "cancellation_date"})
            if calculated.get("status") != "success":
                return calculated
            original_commission = self._decimal(calculated["total_commission"], "total_commission")
        else:
            original_commission = self._money_decimal(self._decimal(original, "original_commission"))

        chargeback = self._chargeback_result(data, schedule_key, original_commission)
        chargeback_amount = self._decimal(chargeback["chargeback_amount"], "chargeback_amount")
        return {
            "status": "success",
            "operation": "apply_chargeback",
            "formula_source": self.formula_source,
            "schedule_key": schedule_key,
            "line_of_business": line,
            "original_commission": self._money(original_commission),
            **chargeback,
            "net_commission_after_chargeback": self._money(original_commission - chargeback_amount),
            "currency": self._currency(data),
        }

    def _effective_schedule_result(self, data: Dict[str, Any]) -> Dict[str, Any]:
        schedule_key, line = self._normalize_product(data)
        effective_date = self._resolve_effective_date(data)
        schedule, period = self._effective_schedule(schedule_key, effective_date)
        return {
            "status": "success",
            "operation": "effective_schedule",
            "formula_source": self.formula_source,
            "schedule_key": schedule_key,
            "line_of_business": line,
            "effective_date": effective_date.isoformat(),
            "schedule": schedule,
            "effective_period": period,
            "effective_dating": self.formulas.get("effective_dating", {}),
        }

    def _chargeback_result(
        self,
        data: Dict[str, Any],
        schedule_key: str,
        original_commission: Decimal,
    ) -> Dict[str, Any]:
        rules = self.formulas.get("chargebacks", {}).get(schedule_key)
        if not rules:
            raise ValueError(f"No chargeback rule configured for {schedule_key}")

        effective_date = self._parse_date(
            data.get("issue_date") or data.get("effective_date") or data.get("transaction_date"),
            "effective_date",
        )
        cancellation_date = self._parse_date(data.get("cancellation_date"), "cancellation_date")
        days_in_force = (cancellation_date - effective_date).days
        if days_in_force < 0:
            raise ValueError("cancellation_date cannot be before effective_date")

        method = rules.get("method", "pro_rata_term")
        if method == "free_look_full_then_pro_rata":
            free_look_days = int(rules.get("free_look_days", 30))
            window_days = int(rules.get("window_days", 365))
            if days_in_force <= free_look_days:
                chargeback_rate = Decimal("1")
            elif days_in_force >= window_days:
                chargeback_rate = Decimal("0")
            else:
                chargeback_rate = Decimal(window_days - days_in_force) / Decimal(window_days)
        elif method == "pro_rata_term":
            term_days = int(data.get("term_days") or rules.get("term_days", 365))
            if days_in_force >= term_days:
                chargeback_rate = Decimal("0")
            else:
                chargeback_rate = Decimal(term_days - days_in_force) / Decimal(term_days)
        else:
            raise ValueError(f"Unsupported chargeback method: {method}")

        chargeback_rate = max(Decimal("0"), min(Decimal("1"), chargeback_rate))
        chargeback_amount = self._money_decimal(original_commission * chargeback_rate)
        return {
            "method": method,
            "effective_date": effective_date.isoformat(),
            "cancellation_date": cancellation_date.isoformat(),
            "days_in_force": days_in_force,
            "chargeback_rate": self._rate(chargeback_rate),
            "chargeback_rate_pct": self._rate_pct(chargeback_rate),
            "chargeback_amount": self._money(chargeback_amount),
        }

    def _effective_schedule(
        self,
        schedule_key: str,
        effective_date: date,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        schedules = self.formulas.get("schedules", {})
        schedule = schedules.get(schedule_key)
        if not schedule:
            raise ValueError(f"No commission schedule configured for {schedule_key}")

        periods = schedule.get("effective_periods") or []
        matched: Optional[Dict[str, Any]] = None
        for period in periods:
            start = self._parse_date(period.get("effective_from"), "effective_from")
            end_raw = period.get("effective_to")
            end = self._parse_date(end_raw, "effective_to") if end_raw else None
            if effective_date >= start and (end is None or effective_date <= end):
                matched = period
        if matched is None:
            raise ValueError(f"No effective commission period for {schedule_key} on {effective_date}")
        return schedule, matched

    def _base_rate(
        self,
        data: Dict[str, Any],
        schedule_key: str,
        line: str,
        period: Dict[str, Any],
    ) -> Tuple[Decimal, str]:
        explicit_rate = data.get("base_rate", data.get("commission_rate"))
        if schedule_key in ("life_fyc", "pc_new"):
            min_rate = self._rate_decimal(period.get("min_rate"), "min_rate")
            max_rate = self._rate_decimal(period.get("max_rate"), "max_rate")
            if explicit_rate is not None:
                rate = self._rate_decimal(explicit_rate, "commission_rate")
                self._validate_rate(rate, min_rate, max_rate, schedule_key)
                return rate, "explicit"

            rates = period.get("rates", {})
            level = self._agent_level(data, period.get("default_level", "standard"))
            raw_rate = rates.get(level)
            if raw_rate is None:
                level = period.get("default_level", "standard")
                raw_rate = rates.get(level)
            rate = self._rate_decimal(raw_rate, f"{schedule_key}.{level}")
            self._validate_rate(rate, min_rate, max_rate, schedule_key)
            return rate, level

        renewal_rules = period.get(line) or period.get("life") or {}
        min_rate = self._rate_decimal(renewal_rules.get("min_rate", 0), "min_rate")
        max_rate = self._rate_decimal(renewal_rules.get("max_rate", 1), "max_rate")
        if explicit_rate is not None:
            rate = self._rate_decimal(explicit_rate, "commission_rate")
            self._validate_rate(rate, min_rate, max_rate, schedule_key)
            return rate, "explicit"

        policy_year = int(data.get("policy_year") or data.get("renewal_year") or 2)
        rate, source = self._renewal_year_rate(renewal_rules.get("year_rates", {}), policy_year)
        if rate is None:
            rate = self._rate_decimal(renewal_rules.get("default_rate", 0), "default_rate")
            source = f"year_{policy_year}_default"
        self._validate_rate(rate, min_rate, max_rate, schedule_key)
        return rate, source

    def _renewal_year_rate(
        self,
        year_rates: Dict[str, Any],
        policy_year: int,
    ) -> Tuple[Optional[Decimal], str]:
        exact = str(policy_year)
        if exact in year_rates:
            return self._rate_decimal(year_rates[exact], f"year_{policy_year}"), f"year_{policy_year}"
        for key, value in year_rates.items():
            if key.endswith("+"):
                try:
                    floor = int(key[:-1])
                except ValueError:
                    continue
                if policy_year >= floor:
                    return self._rate_decimal(value, f"year_{key}"), f"year_{key}"
        return None, ""

    def _override_rows(
        self,
        data: Dict[str, Any],
        schedule_key: str,
        premium: Decimal,
    ) -> List[Dict[str, Any]]:
        hierarchy = data.get("hierarchy") or data.get("upline") or []
        if isinstance(hierarchy, dict):
            hierarchy = [hierarchy]
        if not isinstance(hierarchy, list):
            raise ValueError("hierarchy must be a list of upline entries")

        override_config = self.formulas.get("overrides", {})
        rates_by_level = override_config.get("hierarchy_levels", {})
        max_levels = int(override_config.get("max_levels", 5))
        explicit_rates = data.get("override_rates") or {}
        rows: List[Dict[str, Any]] = []

        for index, entry in enumerate(hierarchy[:max_levels], start=1):
            if not isinstance(entry, dict):
                continue
            level = str(entry.get("level") or entry.get("role") or entry.get("override_level") or "").strip()
            if not level:
                continue
            raw_rate = None
            if isinstance(explicit_rates, dict):
                raw_rate = explicit_rates.get(level)
            if raw_rate is None:
                raw_rate = (rates_by_level.get(level) or {}).get(schedule_key)
            if raw_rate is None:
                continue
            rate = self._rate_decimal(raw_rate, f"override.{level}")
            amount = self._money_decimal(premium * rate)
            rows.append(
                {
                    "agent_id": entry.get("agent_id") or entry.get("id") or "",
                    "level": level,
                    "depth": index,
                    "rate": rate,
                    "_amount": amount,
                }
            )
        return rows

    def _public_override(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "agent_id": row["agent_id"],
            "level": row["level"],
            "depth": row["depth"],
            "rate": self._rate(row["rate"]),
            "rate_pct": self._rate_pct(row["rate"]),
            "amount": self._money(row["_amount"]),
        }

    def _premium_for_schedule(self, data: Dict[str, Any], schedule: Dict[str, Any]) -> Decimal:
        basis = schedule.get("basis", "premium")
        keys = [basis, "premium", "annualized_premium", "written_premium", "renewal_premium"]
        for key in keys:
            if key in data and data[key] is not None:
                premium = self._money_decimal(self._decimal(data[key], key))
                if premium < 0:
                    raise ValueError("premium cannot be negative")
                return premium
        raise ValueError(f"{basis} or premium is required")

    def _normalize_product(self, data: Dict[str, Any]) -> Tuple[str, str]:
        raw = str(
            data.get("schedule_key")
            or data.get("product_type")
            or data.get("line_of_business")
            or "life_fyc"
        ).strip().lower()
        raw = raw.replace("&", "").replace("-", "_").replace(" ", "_")
        transaction_type = str(data.get("transaction_type", "")).strip().lower()
        line = str(data.get("line_of_business", "")).strip().lower().replace("&", "")

        if raw in ("life_fyc", "life_first_year", "first_year_life"):
            return "life_fyc", "life"
        if raw in ("pc_new", "p_c_new", "property_casualty", "property_casualty_new", "pc", "p_c"):
            return "pc_new", "pc"
        if "renew" in raw or transaction_type == "renewal":
            if not line:
                line = "pc" if raw.startswith(("pc", "p_c", "property")) else "life"
            return "renewals", "pc" if line in ("pc", "p_c", "property_casualty") else "life"
        if raw == "life":
            if transaction_type == "renewal":
                return "renewals", "life"
            return "life_fyc", "life"
        raise ValueError(f"Unsupported product_type or schedule_key: {raw}")

    def _agent_level(self, data: Dict[str, Any], default: str) -> str:
        agent = data.get("agent") if isinstance(data.get("agent"), dict) else {}
        return str(data.get("agent_level") or agent.get("level") or default).strip()

    def _resolve_effective_date(self, data: Dict[str, Any]) -> date:
        rules = self.formulas.get("effective_dating", {})
        for field in rules.get("date_field_precedence", []):
            if data.get(field):
                return self._parse_date(data[field], field)
        return date.today()

    def _parse_date(self, value: Any, field: str) -> date:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if not value:
            raise ValueError(f"{field} is required")
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO date") from exc

    def _decimal(self, value: Any, field: str) -> Decimal:
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value).strip().rstrip("%"))
        except (InvalidOperation, AttributeError) as exc:
            raise ValueError(f"{field} must be numeric") from exc

    def _rate_decimal(self, value: Any, field: str) -> Decimal:
        rate = self._decimal(value, field)
        if isinstance(value, str) and value.strip().endswith("%"):
            return rate / Decimal("100")
        if abs(rate) > Decimal("3"):
            return rate / Decimal("100")
        return rate

    def _validate_rate(
        self,
        rate: Decimal,
        min_rate: Decimal,
        max_rate: Decimal,
        schedule_key: str,
    ) -> None:
        if rate < min_rate or rate > max_rate:
            raise ValueError(
                f"{schedule_key} rate {self._rate_pct(rate)}% outside allowed "
                f"{self._rate_pct(min_rate)}%-{self._rate_pct(max_rate)}%"
            )

    def _money_decimal(self, value: Decimal) -> Decimal:
        return value.quantize(CENT, rounding=ROUND_HALF_UP)

    def _money(self, value: Decimal) -> float:
        return float(self._money_decimal(value))

    def _currency(self, data: Dict[str, Any]) -> str:
        """Prefer an explicit policy/request currency, else the schedule default."""

        policy = data.get("policy") if isinstance(data.get("policy"), dict) else {}
        for source in (data, policy):
            value = source.get("currency")
            if value:
                return str(value).upper()
        return str(self.formulas.get("currency", "USD")).upper()

    def _rate(self, value: Decimal) -> float:
        return float(value.quantize(RATE, rounding=ROUND_HALF_UP))

    def _rate_pct(self, value: Decimal) -> float:
        return float((value * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
