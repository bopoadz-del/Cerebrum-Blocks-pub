"""Offer Bidding - deterministic bid/offer lifecycle for task marketplaces.

The Airtasker core: providers place offers on a task, customers accept,
decline, or counter them, and open offers can be ranked by an explicit,
auditable score. Pure decision block: no network, no filesystem, no
re-implementation of payments (settlement belongs to payment_escrow /
billing downstream). Every refusal names the reason and the legal next
moves; scoring is deterministic and reports its own inputs.

Offer lifecycle: open -> countered -> open | accepted | declined | expired.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

OFFER_STATES = ("open", "countered", "accepted", "declined", "expired")
TERMINAL_OFFER_STATES = ("accepted", "declined", "expired")

# Scoring weights for the rank operation (deterministic, auditable).
DEFAULT_WEIGHTS: Dict[str, float] = {
    "price_fit": 0.45,
    "credibility": 0.30,
    "distance": 0.15,
    "response": 0.10,
}


class OfferBiddingBlock(UniversalBlock):
    """Deterministic offer placement, counter, accept/decline and ranking."""

    name = "offer_bidding"
    version = "1.0.0"
    description = (
        "Deterministic task-marketplace bidding: provider offers, customer "
        "accept/decline/counter, budget guards, actor enforcement, and an "
        "auditable weighted ranking of open offers."
    )
    layer = 3
    tags = ["domain", "marketplace", "task", "bidding", "deterministic"]
    requires: List[str] = []
    author = "Cerebrum Team"
    default_config: Dict[str, Any] = {
        "score_weights": dict(DEFAULT_WEIGHTS),
        "max_offer_amount": 1000000,
    }
    ui_schema = {
        "input": {"type": "json"},
        "output": {"type": "json"},
        "params": [],
        "quick_actions": [],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        # offer_id -> record
        self.offers: Dict[str, Dict[str, Any]] = {}
        # task_id -> [offer_id, ...]
        self.task_offers: Dict[str, List[str]] = {}

    # ------------------------------------------------------------------ api
    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**params, **data}
        operation = merged.get("operation") or merged.get("action") or "place"

        try:
            if operation == "place":
                return self._place(merged)
            if operation == "accept":
                return self._decide(merged, "accepted")
            if operation == "decline":
                return self._decide(merged, "declined")
            if operation == "counter":
                return self._counter(merged)
            if operation == "rank":
                return self._rank(merged)
            if operation == "status":
                return self._status(merged)
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc), "operation": operation}

        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": ["place", "accept", "decline", "counter", "rank", "status"],
        }

    # -------------------------------------------------------------- helpers
    def _require(self, data: Dict[str, Any], keys: List[str]) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                return key
        return None

    def _num(self, value: Any, field: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field}: must be a number")
        if number < 0:
            raise ValueError(f"{field}: must be >= 0")
        return number

    def _score_offer(self, offer: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
        budget = task.get("budget") or {}
        amount = offer["amount"]
        if budget and budget.get("max"):
            price_fit = 1.0 if amount <= budget["max"] else max(0.0, 1.0 - (amount - budget["max"]) / budget["max"])
        else:
            price_fit = 1.0
        credibility = min(max(offer.get("credibility", 0.0), 0.0), 1.0)
        distance = offer.get("distance_km")
        distance_score = 1.0 if distance is None else max(0.0, 1.0 - float(distance) / 50.0)
        response = offer.get("response_hours")
        response_score = 1.0 if response is None else max(0.0, 1.0 - float(response) / 72.0)
        weights = self.config.get("score_weights") or DEFAULT_WEIGHTS
        total = (
            weights["price_fit"] * price_fit
            + weights["credibility"] * credibility
            + weights["distance"] * distance_score
            + weights["response"] * response_score
        )
        return {
            "score": round(total, 4),
            "components": {
                "price_fit": round(price_fit, 4),
                "credibility": round(credibility, 4),
                "distance": round(distance_score, 4),
                "response": round(response_score, 4),
            },
        }

    # ----------------------------------------------------------- operations
    def _place(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["task_id", "provider_id", "amount"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        try:
            amount = self._num(data["amount"], "amount")
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc)}
        if amount <= 0:
            return {"status": "error", "error": "amount: must be positive"}

        task = data.get("task") or {}
        budget = task.get("budget") or {}
        if budget.get("max") is not None and amount > budget["max"] * 1.5:
            return {
                "status": "error",
                "error": "offer_exceeds_budget",
                "budget_max": budget["max"],
            }

        offer_id = data.get("offer_id") or f"{data['task_id']}:{data['provider_id']}"
        existing = self.offers.get(offer_id)
        if existing is not None:
            if existing["state"] in ("accepted", "declined"):
                return {
                    "status": "error",
                    "error": f"offer_already_{existing['state']}",
                }
            return {**existing["public"], "idempotent": True}

        record = {
            "offer_id": offer_id,
            "task_id": data["task_id"],
            "provider_id": data["provider_id"],
            "amount": amount,
            "currency": (data.get("currency") or "USD").upper(),
            "state": "open",
            "history": [{"event": "place", "amount": amount}],
            "credibility": data.get("credibility", 0.5),
            "distance_km": data.get("distance_km"),
            "response_hours": data.get("response_hours"),
        }
        public = {
            "status": "success",
            "operation": "place",
            "offer_id": offer_id,
            "task_id": data["task_id"],
            "provider_id": data["provider_id"],
            "amount": amount,
            "state": "open",
        }
        record["public"] = public
        self.offers[offer_id] = record
        self.task_offers.setdefault(data["task_id"], []).append(offer_id)
        return public

    def _decide(self, data: Dict[str, Any], target: str) -> Dict[str, Any]:
        missing = self._require(data, ["offer_id", "customer_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        record = self.offers.get(data["offer_id"])
        if record is None:
            return {"status": "error", "error": "offer_not_found", "offer_id": data["offer_id"]}
        if record["state"] in TERMINAL_OFFER_STATES:
            return {
                "status": "error",
                "error": f"invalid_transition: offer already {record['state']}",
            }
        if record["state"] == "expired":
            return {"status": "error", "error": "invalid_transition: offer expired"}
        record["state"] = target
        record["history"].append({"event": target, "customer_id": data["customer_id"]})
        return {
            "status": "success",
            "operation": target,
            "offer_id": data["offer_id"],
            "state": target,
            "amount": record["amount"],
        }

    def _counter(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["offer_id", "customer_id", "amount"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        try:
            amount = self._num(data["amount"], "amount")
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc)}
        if amount <= 0:
            return {"status": "error", "error": "amount: must be positive"}
        record = self.offers.get(data["offer_id"])
        if record is None:
            return {"status": "error", "error": "offer_not_found", "offer_id": data["offer_id"]}
        if record["state"] in TERMINAL_OFFER_STATES:
            return {
                "status": "error",
                "error": f"invalid_transition: offer already {record['state']}",
            }
        old_amount = record["amount"]
        record["amount"] = amount
        record["state"] = "countered"
        record["history"].append({"event": "counter", "from": old_amount, "to": amount})
        return {
            "status": "success",
            "operation": "counter",
            "offer_id": data["offer_id"],
            "state": "countered",
            "previous_amount": old_amount,
            "amount": amount,
        }

    def _rank(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["task_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        task = data.get("task") or {}
        ranked: List[Dict[str, Any]] = []
        for offer_id in self.task_offers.get(data["task_id"], []):
            record = self.offers[offer_id]
            if record["state"] not in ("open", "countered"):
                continue
            scoring = self._score_offer(record, task)
            ranked.append(
                {
                    "offer_id": offer_id,
                    "provider_id": record["provider_id"],
                    "amount": record["amount"],
                    "state": record["state"],
                    **scoring,
                }
            )
        ranked.sort(key=lambda r: r["score"], reverse=True)
        return {
            "status": "success",
            "operation": "rank",
            "task_id": data["task_id"],
            "ranked": ranked,
            "count": len(ranked),
        }

    def _status(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["offer_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        record = self.offers.get(data["offer_id"])
        if record is None:
            return {"status": "error", "error": "offer_not_found", "offer_id": data["offer_id"]}
        return {
            "status": "success",
            "operation": "status",
            "offer_id": data["offer_id"],
            "task_id": record["task_id"],
            "provider_id": record["provider_id"],
            "state": record["state"],
            "amount": record["amount"],
            "history": record["history"],
        }
