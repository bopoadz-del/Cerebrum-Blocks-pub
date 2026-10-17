"""Pricing Surge - deterministic fare quotes with demand-based surge tiers.

The rideshare/delivery pricing core: base fare plus distance/time
components, a tiered surge multiplier derived from the caller-supplied
demand/supply ratio, hard caps, and fully decomposed auditable totals.
Exact Decimal money math (ROUND_HALF_UP), no network, no filesystem.

Surge tiers are frozen in the config and reported with every quote, so a
price can always be re-derived from its own breakdown.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

CENT = Decimal("0.01")

# (ratio_floor, multiplier) tiers; ratio below the first floor = no surge.
DEFAULT_SURGE_TIERS: List[Tuple[float, str]] = [
    (1.2, "1.25"),
    (2.0, "1.50"),
    (3.0, "2.00"),
]


def money(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid money value: {value!r}")


class PricingSurgeBlock(UniversalBlock):
    """Deterministic fare quoting with tiered surge multipliers."""

    name = "pricing_surge"
    version = "1.0.0"
    description = (
        "Deterministic marketplace pricing: base fare plus distance/time "
        "components, tiered surge multiplier from a caller-supplied "
        "demand/supply ratio with hard caps, and decomposed auditable "
        "totals in exact Decimal math."
    )
    layer = 3
    tags = ["domain", "marketplace", "pricing", "surge", "deterministic"]
    requires: List[str] = []
    author = "Cerebrum Team"
    default_config: Dict[str, Any] = {
        "base_fare": "2.50",
        "per_km": "1.10",
        "per_min": "0.25",
        "surge_tiers": list(DEFAULT_SURGE_TIERS),
        "max_multiplier": "3.00",
        "currency": "USD",
    }
    ui_schema = {
        "input": {"type": "json"},
        "output": {"type": "json"},
        "params": [],
        "quick_actions": [],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)

    # ------------------------------------------------------------------ api
    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**params, **data}
        operation = merged.get("operation") or merged.get("action") or "quote"

        try:
            if operation == "quote":
                return self._quote(merged)
            if operation == "surge":
                return self._surge(merged)
            if operation == "tiers":
                return self._tiers()
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc), "operation": operation}

        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": ["quote", "surge", "tiers"],
        }

    # -------------------------------------------------------------- helpers
    def _require(self, data: Dict[str, Any], keys: List[str]) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                return key
        return None

    def _tier_for_ratio(self, ratio: float) -> Decimal:
        tiers = self.config.get("surge_tiers") or DEFAULT_SURGE_TIERS
        multiplier = Decimal("1.00")
        for floor, mult in tiers:
            if ratio >= float(floor):
                multiplier = money(mult)
            else:
                break
        cap = money(self.config.get("max_multiplier") or "3.00")
        return min(multiplier, cap)

    # ----------------------------------------------------------- operations
    def _surge(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["demand_supply_ratio"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        try:
            ratio = float(data["demand_supply_ratio"])
        except (TypeError, ValueError):
            return {"status": "error", "error": "demand_supply_ratio: must be a number"}
        if ratio < 0:
            return {"status": "error", "error": "demand_supply_ratio: must be >= 0"}
        multiplier = self._tier_for_ratio(ratio)
        return {
            "status": "success",
            "operation": "surge",
            "demand_supply_ratio": ratio,
            "multiplier": str(multiplier),
            "surging": multiplier > Decimal("1.00"),
        }

    def _quote(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["distance_km", "duration_min"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        try:
            distance_km = float(data["distance_km"])
            duration_min = float(data["duration_min"])
            ratio = float(data.get("demand_supply_ratio", 0.0))
        except (TypeError, ValueError):
            return {"status": "error", "error": "distance_km, duration_min, demand_supply_ratio: numbers required"}
        if distance_km < 0 or duration_min < 0 or ratio < 0:
            return {"status": "error", "error": "distance/duration/ratio must be >= 0"}

        base = money(self.config.get("base_fare") or "2.50")
        per_km = money(self.config.get("per_km") or "1.10")
        per_min = money(self.config.get("per_min") or "0.25")
        distance_fee = (per_km * Decimal(str(distance_km))).quantize(CENT, rounding=ROUND_HALF_UP)
        time_fee = (per_min * Decimal(str(duration_min))).quantize(CENT, rounding=ROUND_HALF_UP)
        subtotal = (base + distance_fee + time_fee).quantize(CENT, rounding=ROUND_HALF_UP)

        multiplier = self._tier_for_ratio(ratio)
        surge_amount = (subtotal * (multiplier - Decimal("1.00"))).quantize(CENT, rounding=ROUND_HALF_UP)
        total = (subtotal + surge_amount).quantize(CENT, rounding=ROUND_HALF_UP)
        currency = (data.get("currency") or self.config.get("currency") or "USD").upper()

        return {
            "status": "success",
            "operation": "quote",
            "currency": currency,
            "breakdown": {
                "base_fare": str(base),
                "distance_fee": str(distance_fee),
                "time_fee": str(time_fee),
                "subtotal": str(subtotal),
                "multiplier": str(multiplier),
                "surge_amount": str(surge_amount),
            },
            "total": str(total),
            "inputs": {
                "distance_km": distance_km,
                "duration_min": duration_min,
                "demand_supply_ratio": ratio,
            },
        }

    def _tiers(self) -> Dict[str, Any]:
        tiers = self.config.get("surge_tiers") or DEFAULT_SURGE_TIERS
        return {
            "status": "success",
            "operation": "tiers",
            "surge_tiers": [{"floor": floor, "multiplier": mult} for floor, mult in tiers],
            "max_multiplier": str(self.config.get("max_multiplier") or "3.00"),
            "base_fare": str(self.config.get("base_fare") or "2.50"),
            "per_km": str(self.config.get("per_km") or "1.10"),
            "per_min": str(self.config.get("per_min") or "0.25"),
        }
