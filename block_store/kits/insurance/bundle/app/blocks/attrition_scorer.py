"""Insurance producer attrition scorer using honest deterministic heuristics.

This block is not trained ML and does not claim predictive accuracy. It turns
observable producer/account-manager signals into an explainable risk score so
retention teams can prioritize follow-up and inspect every contribution.
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


def _producer_id(producer: Dict[str, Any], fallback: str) -> str:
    return str(
        producer.get("producer_id")
        or producer.get("id")
        or producer.get("agency_id")
        or producer.get("name")
        or fallback
    )


class AttritionScorerBlock(UniversalBlock):
    """Score insurance producer attrition risk with factor-level explanations."""

    name = "attrition_scorer"
    version = "1.0.0"
    description = "Heuristic insurance producer attrition risk scoring with transparent factor contributions"
    layer = 3
    tags = ["domain", "insurance", "retention", "attrition", "heuristic"]
    requires: List[str] = []

    default_config = {
        "default_operation": "score",
        "low_threshold": 35,
        "high_threshold": 65,
        "critical_threshold": 85,
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"operation": "score", "producer": {"production_trend_pct": -18, "tenure_months": 8, "logins_last_30_days": 2, "complaint_count": 3}}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "risk_band", "type": "text", "label": "Risk Band"},
                {"name": "score", "type": "number", "label": "Risk Score"},
                {"name": "factor_contributions", "type": "list", "label": "Factor Contributions"},
            ],
        },
        "params": [
            {
                "name": "operation",
                "type": "select",
                "label": "Operation",
                "options": ["score", "explain", "batch_score"],
                "default": "score",
            }
        ],
        "quick_actions": [],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {"producer": input_data}
        operation = data.get("operation") or params.get("operation") or params.get("action") or self.config["default_operation"]

        if operation == "score":
            return self._score(self._extract_producer(data, params))
        if operation == "explain":
            scored = self._score(self._extract_producer(data, params))
            scored["operation"] = "explain"
            scored["narrative"] = self._narrative(scored)
            return scored
        if operation == "batch_score":
            return self._batch_score(data, params)
        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": ["score", "explain", "batch_score"],
        }

    def _extract_producer(self, data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        producer = data.get("producer") or data.get("account_manager") or data
        if not isinstance(producer, dict):
            producer = {}
        merged = dict(producer)
        for key, value in params.items():
            merged.setdefault(key, value)
        return merged

    def _batch_score(self, data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        producers = data.get("producers") or data.get("items") or params.get("producers") or []
        if isinstance(producers, dict):
            producers = [producers]
        if not isinstance(producers, Iterable) or isinstance(producers, (str, bytes)):
            return {"status": "error", "error": "batch_score requires a list of producers"}

        results = []
        for index, producer in enumerate(producers):
            if not isinstance(producer, dict):
                continue
            result = self._score(producer)
            result["producer_id"] = _producer_id(producer, f"producer_{index + 1}")
            results.append(result)
        results.sort(key=lambda item: item["score"], reverse=True)
        return {
            "status": "success",
            "operation": "batch_score",
            "results": results,
            "count": len(results),
            "methodology": self._methodology(),
        }

    def _score(self, producer: Dict[str, Any]) -> Dict[str, Any]:
        raw_score, contributions = self._factor_contributions(producer)
        score = max(0, min(100, round(raw_score)))
        band = self._risk_band(score)
        return {
            "status": "success",
            "operation": "score",
            "producer_id": _producer_id(producer, "producer"),
            "risk_band": band,
            "score": score,
            "factor_contributions": contributions,
            "top_factors": sorted(contributions, key=lambda item: item["contribution"], reverse=True)[:3],
            "methodology": self._methodology(),
        }

    def _factor_contributions(self, producer: Dict[str, Any]) -> Tuple[float, List[Dict[str, Any]]]:
        score = 30.0
        contributions: List[Dict[str, Any]] = []

        def add(factor: str, contribution: float, observed: Any, rationale: str) -> None:
            nonlocal score
            score += contribution
            contributions.append(
                {
                    "factor": factor,
                    "observed": observed,
                    "contribution": round(contribution, 1),
                    "rationale": rationale,
                }
            )

        trend = self._production_trend(producer)
        if trend <= -25:
            add("production_trend", 26, trend, "production has fallen sharply")
        elif trend <= -10:
            add("production_trend", 16, trend, "production is down materially")
        elif trend < 0:
            add("production_trend", 7, trend, "production is slightly down")
        elif trend >= 15:
            add("production_trend", -12, trend, "production growth lowers attrition concern")
        else:
            add("production_trend", -3, trend, "production is broadly stable")

        tenure_months = self._tenure_months(producer)
        if tenure_months and tenure_months < 6:
            add("tenure", 14, tenure_months, "very new producer relationship has higher onboarding risk")
        elif tenure_months and tenure_months < 18:
            add("tenure", 7, tenure_months, "early-tenure producer may still be evaluating fit")
        elif tenure_months >= 48:
            add("tenure", -8, tenure_months, "long tenure lowers near-term attrition concern")
        else:
            add("tenure", 0, tenure_months, "tenure is neutral")

        logins = _as_float(
            producer.get("logins_last_30_days")
            or producer.get("login_count_30d")
            or producer.get("portal_logins_30d")
        )
        if logins <= 1:
            add("login_frequency", 18, logins, "minimal portal usage suggests disengagement")
        elif logins < 5:
            add("login_frequency", 9, logins, "low portal usage suggests weakening engagement")
        elif logins >= 20:
            add("login_frequency", -7, logins, "frequent portal usage indicates active engagement")
        else:
            add("login_frequency", -2, logins, "portal usage is normal")

        complaints = _as_float(producer.get("complaint_count") or producer.get("complaints_last_90_days"))
        if complaints >= 5:
            add("complaint_count", 20, complaints, "multiple complaints are a strong retention risk signal")
        elif complaints >= 2:
            add("complaint_count", 11, complaints, "recent complaints increase retention risk")
        elif complaints == 0:
            add("complaint_count", -4, complaints, "no recent complaints lowers risk")
        else:
            add("complaint_count", 3, complaints, "one recent complaint is a mild risk signal")

        missed_targets = _as_float(producer.get("missed_targets") or producer.get("missed_target_count"))
        if missed_targets >= 3:
            add("missed_targets", 10, missed_targets, "repeated missed goals can precede disengagement")
        elif missed_targets > 0:
            add("missed_targets", 4, missed_targets, "some missed goals add mild concern")
        else:
            add("missed_targets", -2, missed_targets, "no missed targets is favorable")

        service_tickets = _as_float(producer.get("open_service_tickets") or producer.get("open_cases"))
        if service_tickets >= 4:
            add("open_service_tickets", 8, service_tickets, "unresolved service issues can drive attrition")
        elif service_tickets == 0:
            add("open_service_tickets", -2, service_tickets, "no open service issues is favorable")
        else:
            add("open_service_tickets", 2, service_tickets, "open service issues add mild concern")

        nps = producer.get("nps") or producer.get("satisfaction_score")
        if nps is not None:
            nps_value = _as_float(nps)
            if nps_value <= 3:
                add("satisfaction", 12, nps_value, "low satisfaction score increases attrition concern")
            elif nps_value >= 8:
                add("satisfaction", -8, nps_value, "high satisfaction score lowers concern")
            else:
                add("satisfaction", 0, nps_value, "satisfaction score is neutral")

        return score, contributions

    def _production_trend(self, producer: Dict[str, Any]) -> float:
        explicit = producer.get("production_trend_pct") or producer.get("production_growth_pct")
        if explicit is not None:
            return _as_float(explicit)
        current = _as_float(producer.get("production_current") or producer.get("current_production"))
        previous = _as_float(producer.get("production_previous") or producer.get("prior_production"))
        if previous == 0:
            return 0.0
        return ((current - previous) / previous) * 100

    def _tenure_months(self, producer: Dict[str, Any]) -> float:
        if producer.get("tenure_months") is not None:
            return _as_float(producer.get("tenure_months"))
        return _as_float(producer.get("tenure_years")) * 12

    def _risk_band(self, score: float) -> str:
        if score >= self.config["critical_threshold"]:
            return "critical"
        if score >= self.config["high_threshold"]:
            return "high"
        if score >= self.config["low_threshold"]:
            return "medium"
        return "low"

    def _narrative(self, scored: Dict[str, Any]) -> str:
        top = scored.get("top_factors") or []
        if not top:
            return "No material risk drivers were found in the supplied data."
        drivers = ", ".join(f"{item['factor']} ({item['contribution']:+.0f})" for item in top)
        return f"Risk band is {scored['risk_band']} with score {scored['score']}/100. Main drivers: {drivers}."

    def _methodology(self) -> str:
        return (
            "Honest heuristic scoring only; not trained ML and not a prediction guarantee. "
            "Score starts from a baseline and adds factor contributions for production trend, "
            "tenure, login frequency, complaints, missed targets, service tickets, and satisfaction when provided."
        )
