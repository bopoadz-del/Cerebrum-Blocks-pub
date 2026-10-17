"""Insurance channel router with explainable heuristic scoring.

The block is intentionally self-contained and deterministic: it does not import
the orchestrator or any trained model. Scores are simple weighted rules that
help compare agency, direct, MGA, and partner channels for an account.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.core.universal_base import UniversalBlock


_CHANNELS: Dict[str, Dict[str, Any]] = {
    "agency": {
        "label": "Agency",
        "best_for": [
            "relationship-led accounts",
            "commercial or mid-market risks",
            "customers needing advice or local service",
        ],
        "watchouts": ["slower than fully digital intake", "commission-sensitive economics"],
    },
    "direct": {
        "label": "Direct",
        "best_for": [
            "simple personal lines",
            "digitally engaged customers",
            "low-touch quotes where speed matters",
        ],
        "watchouts": ["limited suitability for complex underwriting", "less producer advocacy"],
    },
    "mga": {
        "label": "MGA",
        "best_for": [
            "specialty or hard-to-place risk",
            "niche products with delegated authority",
            "higher complexity submissions",
        ],
        "watchouts": ["program appetite limits", "capacity and delegated authority constraints"],
    },
    "partner": {
        "label": "Partner",
        "best_for": [
            "embedded or affinity distribution",
            "referred customers",
            "bundled offerings with a sponsor or platform",
        ],
        "watchouts": ["dependency on partner data quality", "brand/control tradeoffs"],
    },
}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "high"}
    return bool(value)


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


class ChannelRouterBlock(UniversalBlock):
    """Route insurance accounts to distribution channels using transparent rules."""

    name = "channel_router"
    version = "1.0.0"
    description = "Explainable insurance channel routing for agency, direct, MGA, and partner channels"
    layer = 3
    tags = ["domain", "insurance", "routing", "distribution", "heuristic"]
    requires: List[str] = []

    default_config = {
        "default_operation": "route",
        "minimum_confidence_gap": 8,
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"operation": "route", "account": {"line_of_business": "commercial_property", "premium": 75000, "complexity": "high"}}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "recommended_channel", "type": "text", "label": "Recommended Channel"},
                {"name": "score", "type": "number", "label": "Top Score"},
                {"name": "explanation", "type": "text", "label": "Explanation"},
            ],
        },
        "params": [
            {
                "name": "operation",
                "type": "select",
                "label": "Operation",
                "options": ["route", "list_channels", "score_channels"],
                "default": "route",
            }
        ],
        "quick_actions": [],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {"account": input_data}
        operation = data.get("operation") or params.get("operation") or params.get("action") or self.config["default_operation"]

        if operation == "list_channels":
            return self._list_channels()
        if operation == "score_channels":
            account = self._extract_account(data, params)
            return self._score_channels(account)
        if operation == "route":
            account = self._extract_account(data, params)
            return self._route(account)
        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": ["route", "list_channels", "score_channels"],
        }

    def _extract_account(self, data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        account = data.get("account") or data.get("submission") or data.get("customer") or data
        if not isinstance(account, dict):
            account = {}
        merged = dict(account)
        for key in (
            "line_of_business",
            "premium",
            "complexity",
            "digital_preference",
            "relationship_strength",
            "specialty_risk",
            "partner_referral",
            "speed_priority",
            "needs_advice",
            "channel_constraints",
        ):
            if key in params and key not in merged:
                merged[key] = params[key]
        return merged

    def _list_channels(self) -> Dict[str, Any]:
        return {
            "status": "success",
            "operation": "list_channels",
            "channels": [
                {"channel": key, **profile}
                for key, profile in _CHANNELS.items()
            ],
            "methodology": "Static channel catalog for insurance distribution planning.",
        }

    def _route(self, account: Dict[str, Any]) -> Dict[str, Any]:
        scored = self._score_channels(account)
        top = scored["ranked_channels"][0]
        runner_up = scored["ranked_channels"][1] if len(scored["ranked_channels"]) > 1 else None
        gap = top["score"] - (runner_up["score"] if runner_up else 0)
        confidence = "high" if gap >= self.config["minimum_confidence_gap"] else "medium"
        if gap < 4:
            confidence = "low"
        return {
            "status": "success",
            "operation": "route",
            "recommended_channel": top["channel"],
            "score": top["score"],
            "confidence": confidence,
            "explanation": top["explanation"],
            "runner_up": runner_up,
            "ranked_channels": scored["ranked_channels"],
            "methodology": scored["methodology"],
        }

    def _score_channels(self, account: Dict[str, Any]) -> Dict[str, Any]:
        scores = []
        for channel in _CHANNELS:
            score, factors = self._channel_score(channel, account)
            explanation = self._explain_channel(channel, factors)
            scores.append(
                {
                    "channel": channel,
                    "label": _CHANNELS[channel]["label"],
                    "score": max(0, min(100, round(score, 1))),
                    "factors": factors,
                    "explanation": explanation,
                }
            )
        scores.sort(key=lambda item: item["score"], reverse=True)
        return {
            "status": "success",
            "operation": "score_channels",
            "ranked_channels": scores,
            "methodology": "Deterministic heuristic scoring; not trained ML. Factor contributions are additive and clamped to 0-100.",
        }

    def _channel_score(self, channel: str, account: Dict[str, Any]) -> Tuple[float, List[Dict[str, Any]]]:
        factors: List[Dict[str, Any]] = []
        score = 50.0

        def add(name: str, contribution: float, reason: str) -> None:
            nonlocal score
            score += contribution
            factors.append(
                {
                    "factor": name,
                    "contribution": round(contribution, 1),
                    "reason": reason,
                }
            )

        premium = _as_float(account.get("premium") or account.get("annual_premium"))
        complexity = _norm(account.get("complexity") or account.get("risk_complexity"))
        lob = _norm(account.get("line_of_business") or account.get("lob") or account.get("product"))
        relationship = _norm(account.get("relationship_strength") or account.get("agency_relationship"))
        digital = _as_bool(account.get("digital_preference") or account.get("self_service_preference"))
        specialty = _as_bool(account.get("specialty_risk") or account.get("hard_to_place"))
        partner_referral = _as_bool(account.get("partner_referral") or account.get("affinity_referral"))
        speed = _as_bool(account.get("speed_priority") or account.get("fast_quote_needed"))
        advice = _as_bool(account.get("needs_advice") or account.get("advice_needed"))
        constraints = account.get("channel_constraints") or []
        if isinstance(constraints, str):
            constraints = [constraints]
        constraints = {_norm(item) for item in constraints}

        if channel in constraints:
            add("channel_constraints", -40, f"{channel} is constrained or excluded for this submission")

        if channel == "agency":
            if relationship in {"strong", "existing", "preferred"}:
                add("relationship_strength", 18, "existing producer relationship favors agency handling")
            if complexity in {"medium", "high", "complex"}:
                add("complexity", 12, "complex risk benefits from producer advice")
            if premium >= 25000:
                add("premium", 8, "larger premium supports advised distribution economics")
            if advice:
                add("advice_needed", 14, "customer needs advice or coverage review")
            if digital and complexity in {"low", "simple"}:
                add("digital_simple", -8, "simple digital-first submission may fit direct better")
        elif channel == "direct":
            if digital:
                add("digital_preference", 18, "digital/self-service preference favors direct")
            if complexity in {"low", "simple", ""}:
                add("complexity", 12, "low-complexity submission fits direct intake")
            if speed:
                add("speed_priority", 10, "fast quote priority favors direct workflow")
            if premium and premium < 10000:
                add("premium", 8, "smaller premium can be economical through direct")
            if advice or specialty:
                add("advice_or_specialty", -18, "advice or specialty underwriting weakens direct fit")
        elif channel == "mga":
            if specialty:
                add("specialty_risk", 24, "specialty or hard-to-place risk favors MGA appetite")
            if complexity in {"high", "complex"}:
                add("complexity", 14, "complex underwriting can benefit from delegated expertise")
            if lob in {"professional_liability", "cyber", "surplus_lines", "e_s", "excess_surplus", "specialty"}:
                add("line_of_business", 16, f"{lob} often routes through specialty programs")
            if premium >= 50000:
                add("premium", 6, "larger premium supports specialty placement work")
            if digital and complexity in {"low", "simple"}:
                add("digital_simple", -12, "simple digital submission is usually not an MGA-first fit")
        elif channel == "partner":
            if partner_referral:
                add("partner_referral", 22, "partner or affinity source should preserve the partner path")
            if lob in {"embedded", "affinity", "travel", "device", "warranty", "pet"}:
                add("line_of_business", 14, f"{lob} aligns with partner distribution")
            if digital:
                add("digital_preference", 8, "digital journey can be embedded with partner")
            if complexity in {"low", "simple"}:
                add("complexity", 8, "simple products fit embedded partner flows")
            if advice or complexity in {"high", "complex"}:
                add("advice_or_complexity", -12, "high-advice cases are harder to handle through partners")

        if not factors:
            add("baseline", 0, "no strong fit signals provided; channel remains at baseline")
        return score, factors

    def _explain_channel(self, channel: str, factors: List[Dict[str, Any]]) -> str:
        positive = [item for item in factors if item["contribution"] > 0]
        negative = [item for item in factors if item["contribution"] < 0]
        if positive:
            lead = max(positive, key=lambda item: item["contribution"])
            text = f"{_CHANNELS[channel]['label']} scores highest on {lead['factor']}: {lead['reason']}."
        else:
            text = f"{_CHANNELS[channel]['label']} has no strong positive fit signals."
        if negative:
            drag = min(negative, key=lambda item: item["contribution"])
            text += f" Main offset: {drag['reason']}."
        return text
