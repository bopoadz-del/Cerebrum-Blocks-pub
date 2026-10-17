"""Insurance incentive targeting using formula-like heuristic rules.

This block does not use ML or make accuracy claims. It ranks producers and
allocates incentive budgets with transparent eligibility and bonus formulas.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from app.core.universal_base import UniversalBlock


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    return int(round(_as_float(value, default)))


def _producer_id(producer: Dict[str, Any], fallback: str) -> str:
    return str(producer.get("producer_id") or producer.get("id") or producer.get("agency_id") or producer.get("name") or fallback)


class IncentiveTargetingBlock(UniversalBlock):
    """Rank producers and target incentives with transparent business rules."""

    name = "incentive_targeting"
    version = "1.0.0"
    description = "Heuristic insurance producer incentive targeting and budget simulation"
    layer = 3
    tags = ["domain", "insurance", "incentives", "producer-management", "heuristic"]
    requires: List[str] = []

    default_config = {
        "default_operation": "target",
        "min_retention_rate": 0.82,
        "max_loss_ratio": 0.68,
        "min_growth_pct": 5.0,
        "min_premium": 50000.0,
        "base_bonus_rate": 0.015,
        "growth_bonus_rate": 0.01,
        "strategic_product_bonus": 250.0,
        "default_budget": 25000.0,
        "max_bonus_per_producer": 7500.0,
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"operation": "target", "producer": {"production": 125000, "growth_pct": 12, "retention_rate": 0.9, "loss_ratio": 0.52}}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "eligible", "type": "boolean", "label": "Eligible"},
                {"name": "recommended_bonus", "type": "number", "label": "Recommended Bonus"},
                {"name": "rank_score", "type": "number", "label": "Rank Score"},
            ],
        },
        "params": [
            {
                "name": "operation",
                "type": "select",
                "label": "Operation",
                "options": ["target", "simulate_budget", "rank_producers"],
                "default": "target",
            }
        ],
        "quick_actions": [],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {"producer": input_data}
        operation = data.get("operation") or params.get("operation") or params.get("action") or self.config["default_operation"]

        if operation == "target":
            return self._target(data, params)
        if operation == "simulate_budget":
            return self._simulate_budget(data, params)
        if operation == "rank_producers":
            return self._rank_producers(data, params)
        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": ["target", "simulate_budget", "rank_producers"],
        }

    def _target(self, data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        producers = self._extract_producers(data, params)
        if len(producers) > 1:
            ranked = [self._evaluate(producer, index) for index, producer in enumerate(producers)]
            ranked.sort(key=lambda item: item["rank_score"], reverse=True)
            return {
                "status": "success",
                "operation": "target",
                "targets": ranked,
                "top_target": ranked[0] if ranked else None,
                "methodology": self._methodology(),
            }
        producer = producers[0] if producers else self._extract_producer(data, params)
        result = self._evaluate(producer, 0)
        result.update({"status": "success", "operation": "target", "methodology": self._methodology()})
        return result

    def _simulate_budget(self, data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        producers = self._extract_producers(data, params)
        budget = _as_float(data.get("budget") or data.get("budget_amount") or params.get("budget"), self.config["default_budget"])
        cap = _as_float(
            data.get("max_bonus_per_producer") or params.get("max_bonus_per_producer"),
            self.config["max_bonus_per_producer"],
        )
        ranked = [self._evaluate(producer, index) for index, producer in enumerate(producers)]
        ranked.sort(key=lambda item: item["rank_score"], reverse=True)

        allocations = []
        remaining = budget
        for item in ranked:
            requested = min(item["recommended_bonus"], cap)
            allocated = min(requested, remaining) if item["eligible"] else 0.0
            remaining -= allocated
            allocation = dict(item)
            allocation["requested_bonus"] = round(requested, 2)
            allocation["allocated_bonus"] = round(allocated, 2)
            allocation["funded"] = allocated > 0
            allocations.append(allocation)
            if remaining <= 0:
                remaining = 0.0

        return {
            "status": "success",
            "operation": "simulate_budget",
            "budget": round(budget, 2),
            "allocated": round(budget - remaining, 2),
            "remaining": round(remaining, 2),
            "allocations": allocations,
            "methodology": self._methodology(),
        }

    def _rank_producers(self, data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        producers = self._extract_producers(data, params)
        ranked = [self._evaluate(producer, index) for index, producer in enumerate(producers)]
        ranked.sort(key=lambda item: item["rank_score"], reverse=True)
        for rank, item in enumerate(ranked, start=1):
            item["rank"] = rank
        return {
            "status": "success",
            "operation": "rank_producers",
            "ranked_producers": ranked,
            "count": len(ranked),
            "methodology": self._methodology(),
        }

    def _extract_producer(self, data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        producer = data.get("producer") or data.get("agency") or data
        if not isinstance(producer, dict):
            producer = {}
        merged = dict(producer)
        for key, value in params.items():
            merged.setdefault(key, value)
        return merged

    def _extract_producers(self, data: Dict[str, Any], params: Dict[str, Any]) -> List[Dict[str, Any]]:
        producers = data.get("producers") or data.get("agencies") or params.get("producers")
        if producers is None and data.get("producer"):
            producers = [data["producer"]]
        if producers is None:
            return []
        if isinstance(producers, dict):
            producers = [producers]
        if not isinstance(producers, Iterable) or isinstance(producers, (str, bytes)):
            return []
        return [producer for producer in producers if isinstance(producer, dict)]

    def _evaluate(self, producer: Dict[str, Any], index: int) -> Dict[str, Any]:
        eligibility, reasons = self._eligibility(producer)
        rank_score, rank_factors = self._rank_score(producer)
        bonus, formula = self._bonus(producer, eligibility)
        return {
            "producer_id": _producer_id(producer, f"producer_{index + 1}"),
            "eligible": eligibility,
            "recommended_bonus": round(bonus, 2),
            "rank_score": round(rank_score, 1),
            "eligibility_reasons": reasons,
            "rank_factors": rank_factors,
            "formula": formula,
        }

    def _eligibility(self, producer: Dict[str, Any]) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        production = _as_float(producer.get("production") or producer.get("written_premium") or producer.get("premium"))
        growth = _as_float(producer.get("growth_pct") or producer.get("production_growth_pct"))
        retention = self._ratio(producer.get("retention_rate") or producer.get("renewal_retention"))
        loss_ratio = self._ratio(producer.get("loss_ratio"))
        compliance_issues = _as_int(producer.get("compliance_issues") or producer.get("open_compliance_findings"))
        complaints = _as_int(producer.get("complaint_count") or producer.get("complaints_last_90_days"))

        if compliance_issues > 0:
            reasons.append("ineligible: open compliance issues")
        if complaints >= 5:
            reasons.append("ineligible: complaint count exceeds tolerance")
        if retention < self.config["min_retention_rate"]:
            reasons.append(f"retention below {self.config['min_retention_rate']:.0%}")
        if loss_ratio > self.config["max_loss_ratio"]:
            reasons.append(f"loss ratio above {self.config['max_loss_ratio']:.0%}")
        if production < self.config["min_premium"] and growth < self.config["min_growth_pct"]:
            reasons.append("production and growth are both below incentive threshold")

        if not reasons:
            reasons.append("eligible: quality, retention, growth, and compliance thresholds satisfied")
        return all(not reason.startswith("ineligible") for reason in reasons) and retention >= self.config["min_retention_rate"] and loss_ratio <= self.config["max_loss_ratio"] and (production >= self.config["min_premium"] or growth >= self.config["min_growth_pct"]), reasons

    def _rank_score(self, producer: Dict[str, Any]) -> Tuple[float, List[Dict[str, Any]]]:
        production = _as_float(producer.get("production") or producer.get("written_premium") or producer.get("premium"))
        growth = _as_float(producer.get("growth_pct") or producer.get("production_growth_pct"))
        retention = self._ratio(producer.get("retention_rate") or producer.get("renewal_retention"))
        loss_ratio = self._ratio(producer.get("loss_ratio"))
        strategic_products = _as_int(producer.get("strategic_products") or producer.get("strategic_product_count"))

        factors = [
            {
                "factor": "production",
                "contribution": min(30.0, production / 10000.0),
                "rationale": "larger production supports higher incentive priority",
            },
            {
                "factor": "growth",
                "contribution": max(-10.0, min(25.0, growth)),
                "rationale": "growth percentage is rewarded but capped",
            },
            {
                "factor": "retention",
                "contribution": max(0.0, min(20.0, (retention - 0.75) * 100)),
                "rationale": "retention above 75% improves rank",
            },
            {
                "factor": "loss_ratio",
                "contribution": max(-20.0, min(15.0, (0.70 - loss_ratio) * 100)),
                "rationale": "lower loss ratio improves rank; high loss ratio penalizes",
            },
            {
                "factor": "strategic_products",
                "contribution": min(10.0, strategic_products * 2.5),
                "rationale": "strategic product placements earn extra priority",
            },
        ]
        score = 50.0 + sum(item["contribution"] for item in factors)
        for item in factors:
            item["contribution"] = round(item["contribution"], 1)
        return max(0.0, min(100.0, score)), factors

    def _bonus(self, producer: Dict[str, Any], eligible: bool) -> Tuple[float, str]:
        production = _as_float(producer.get("production") or producer.get("written_premium") or producer.get("premium"))
        target = _as_float(producer.get("target_premium") or producer.get("production_target"))
        growth = max(0.0, _as_float(producer.get("growth_pct") or producer.get("production_growth_pct")))
        strategic_products = _as_int(producer.get("strategic_products") or producer.get("strategic_product_count"))
        incremental = max(0.0, production - target) if target else max(0.0, production * growth / 100.0)

        if not eligible:
            return 0.0, "not eligible, so recommended_bonus = 0"
        base = production * self.config["base_bonus_rate"]
        growth_bonus = incremental * self.config["growth_bonus_rate"]
        strategic_bonus = strategic_products * self.config["strategic_product_bonus"]
        total = min(base + growth_bonus + strategic_bonus, self.config["max_bonus_per_producer"])
        formula = (
            f"min(production * {self.config['base_bonus_rate']:.3f} "
            f"+ incremental_premium * {self.config['growth_bonus_rate']:.3f} "
            f"+ strategic_products * {self.config['strategic_product_bonus']:.0f}, "
            f"{self.config['max_bonus_per_producer']:.0f})"
        )
        return total, "".join(formula)

    def _ratio(self, value: Any) -> float:
        ratio = _as_float(value)
        if ratio > 1:
            ratio = ratio / 100.0
        return ratio

    def _methodology(self) -> str:
        return (
            "Heuristic targeting only; not ML. Eligibility requires compliance health, "
            "retention above threshold, loss ratio below threshold, and either production "
            "or growth above threshold. Bonus uses transparent production, incremental "
            "premium, and strategic-product formula components."
        )
