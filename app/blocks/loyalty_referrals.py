"""Loyalty Referrals - deterministic referral credits and redemption.

The marketplace growth loop: referred signups grant credits to both
parties (capped uses per referrer), credits carry a caller-supplied
expiry step, redemption burns oldest-first against a purchase amount
with exact Decimal math, and balances are always re-derivable from the
ledger. Pure decision block: no network, no filesystem, no wall clock -
expiry compares caller-supplied step numbers.

Fail-closed: negative amounts refused, self-referral refused, redemption
beyond balance refused, duplicate referral keys refused.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

CENT = Decimal("0.01")


def money(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid money value: {value!r}")


class LoyaltyReferralsBlock(UniversalBlock):
    """Deterministic referral credits with capped rewards and FIFO redemption."""

    name = "loyalty_referrals"
    version = "1.0.0"
    description = (
        "Deterministic marketplace loyalty: two-sided referral credits with "
        "capped uses per referrer, sequence-based expiry, FIFO redemption "
        "against purchases, and a fully auditable ledger in exact Decimal "
        "money math."
    )
    layer = 3
    tags = ["domain", "marketplace", "loyalty", "referrals", "deterministic"]
    requires: List[str] = []
    author = "Cerebrum Team"
    default_config: Dict[str, Any] = {
        "referrer_reward": "10.00",
        "referee_reward": "5.00",
        "max_referrals_per_user": 20,
        "default_expiry_steps": 1000,
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
        # user_id -> [credit rows: {id, amount, reason, issued_step, expiry_step, remaining}]
        self.ledger: Dict[str, List[Dict[str, Any]]] = {}
        self.referral_keys: set = set()
        self.referral_counts: Dict[str, int] = {}

    # ------------------------------------------------------------------ api
    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**params, **data}
        operation = merged.get("operation") or merged.get("action") or "referral"

        try:
            if operation == "referral":
                return self._referral(merged)
            if operation == "issue_credit":
                return self._issue_credit(merged)
            if operation == "redeem":
                return self._redeem(merged)
            if operation == "balance":
                return self._balance(merged)
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc), "operation": operation}

        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": ["referral", "issue_credit", "redeem", "balance"],
        }

    # -------------------------------------------------------------- helpers
    def _require(self, data: Dict[str, Any], keys: List[str]) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                return key
        return None

    def _active_rows(self, user_id: str, step: int) -> List[Dict[str, Any]]:
        rows = self.ledger.get(user_id, [])
        return [r for r in rows if r["expiry_step"] > step and r["remaining"] > 0]

    # ----------------------------------------------------------- operations
    def _referral(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["referral_key", "referrer_id", "referee_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        if data["referrer_id"] == data["referee_id"]:
            return {"status": "error", "error": "self_referral_refused"}
        if data["referral_key"] in self.referral_keys:
            return {"status": "error", "error": "referral_key_already_used"}
        cap = int(self.config.get("max_referrals_per_user") or 20)
        used = self.referral_counts.get(data["referrer_id"], 0)
        if used >= cap:
            return {"status": "error", "error": "referral_cap_reached", "cap": cap}

        step = int(data.get("step", 0))
        self.referral_keys.add(data["referral_key"])
        self.referral_counts[data["referrer_id"]] = used + 1
        self._grant(data["referrer_id"], money(self.config.get("referrer_reward") or "10.00"), "referral", step)
        self._grant(data["referee_id"], money(self.config.get("referee_reward") or "5.00"), "signup_bonus", step)
        return {
            "status": "success",
            "operation": "referral",
            "referral_key": data["referral_key"],
            "referrer_id": data["referrer_id"],
            "referee_id": data["referee_id"],
            "referrer_reward": str(self.config.get("referrer_reward") or "10.00"),
            "referee_reward": str(self.config.get("referee_reward") or "5.00"),
            "referrer_uses": self.referral_counts[data["referrer_id"]],
        }

    def _grant(self, user_id: str, amount: Decimal, reason: str, step: int) -> None:
        expiry = step + int(self.config.get("default_expiry_steps") or 1000)
        row = {
            "id": f"{user_id}:{step}:{reason}",
            "amount": amount,
            "remaining": amount,
            "reason": reason,
            "issued_step": step,
            "expiry_step": expiry,
        }
        self.ledger.setdefault(user_id, []).append(row)

    def _issue_credit(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["user_id", "amount", "reason"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        try:
            amount = money(data["amount"])
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc)}
        if amount <= 0:
            return {"status": "error", "error": "amount: must be positive"}
        step = int(data.get("step", 0))
        self._grant(data["user_id"], amount, data["reason"], step)
        return {
            "status": "success",
            "operation": "issue_credit",
            "user_id": data["user_id"],
            "amount": str(amount),
            "reason": data["reason"],
        }

    def _redeem(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["user_id", "amount"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        try:
            amount = money(data["amount"])
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc)}
        if amount <= 0:
            return {"status": "error", "error": "amount: must be positive"}
        step = int(data.get("step", 0))
        rows = sorted(self._active_rows(data["user_id"], step), key=lambda r: (r["issued_step"], r["id"]))
        available = sum((r["remaining"] for r in rows), Decimal("0.00"))
        if amount > available:
            return {
                "status": "error",
                "error": "insufficient_balance",
                "available": str(available),
            }
        remaining = amount
        applied: List[Dict[str, str]] = []
        for row in rows:
            if remaining <= 0:
                break
            take = min(row["remaining"], remaining)
            row["remaining"] = (row["remaining"] - take).quantize(CENT, rounding=ROUND_HALF_UP)
            applied.append({"credit_id": row["id"], "amount": str(take)})
            remaining = (remaining - take).quantize(CENT, rounding=ROUND_HALF_UP)
        return {
            "status": "success",
            "operation": "redeem",
            "user_id": data["user_id"],
            "redeemed": str(amount),
            "applied": applied,
            "balance_after": str(sum((r["remaining"] for r in self._active_rows(data["user_id"], step)), Decimal("0.00"))),
        }

    def _balance(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["user_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        step = int(data.get("step", 0))
        rows = self._active_rows(data["user_id"], step)
        total = sum((r["remaining"] for r in rows), Decimal("0.00"))
        return {
            "status": "success",
            "operation": "balance",
            "user_id": data["user_id"],
            "balance": str(total),
            "credit_count": len(rows),
        }
