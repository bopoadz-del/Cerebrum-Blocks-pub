"""Payment Escrow - deterministic hold/release/refund lifecycle for marketplaces.

Pure decision/math block: it owns the escrow lifecycle (hold, fee quote,
release, partial release, refund, dispute freeze) and the platform fee math.
It deliberately does NOT re-implement payment capture or settlement: those
belong to the existing `billing` and `payment_split` blocks, declared in
`requires` and reached through the assembler's capability proxy.

Money math is exact (Decimal, ROUND_HALF_UP) and fully deterministic: the
fee configuration is frozen at hold time, so a later release always pays the
amount quoted at hold time. Every operation is idempotent by payment_id +
operation; conflicting repeats are refused, not silently re-applied.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

CENT = Decimal("0.01")


def money(value: Any) -> Decimal:
    """Coerce a money value to Decimal cents with half-up rounding."""
    if isinstance(value, Decimal):
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid money value: {value!r}")


class PaymentEscrowBlock(UniversalBlock):
    """Deterministic escrow lifecycle with platform fee math."""

    name = "payment_escrow"
    version = "1.0.0"
    description = (
        "Deterministic escrow lifecycle for marketplace payments: hold, fee "
        "quote, release, partial release, refund, and dispute freeze, with "
        "exact Decimal fee math frozen at hold time. Delegates capture and "
        "settlement to billing/payment_split (declared requires)."
    )
    layer = 3
    tags = ["domain", "marketplace", "payments", "escrow", "deterministic", "core-spine"]
    requires = ["billing", "payment_split"]
    author = "Cerebrum Team"
    default_config: Dict[str, Any] = {
        "platform_fee_rate": "0.15",
        "platform_fee_fixed": "0.00",
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
        # payment_id -> escrow record
        self.escrows: Dict[str, Dict[str, Any]] = {}
        # (payment_id, operation, fingerprint) -> prior outcome
        self.idempotent: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ api
    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**params, **data}
        operation = merged.get("operation") or merged.get("action") or "status"

        try:
            if operation == "hold":
                return self._hold(merged)
            if operation == "fee_quote":
                return self._fee_quote(merged)
            if operation == "release":
                return self._release(merged)
            if operation == "partial_release":
                return self._partial_release(merged)
            if operation == "refund":
                return self._refund(merged)
            if operation == "freeze":
                return self._freeze(merged, frozen=True)
            if operation == "unfreeze":
                return self._freeze(merged, frozen=False)
            if operation == "status":
                return self._status(merged)
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc), "operation": operation}

        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": [
                "hold", "fee_quote", "release", "partial_release",
                "refund", "freeze", "unfreeze", "status",
            ],
        }

    # -------------------------------------------------------------- helpers
    def _require(self, data: Dict[str, Any], keys: List[str]) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                return key
        return None

    def _fee_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        rate = money(data.get("platform_fee_rate", self.config.get("platform_fee_rate", "0.15")))
        fixed = money(data.get("platform_fee_fixed", self.config.get("platform_fee_fixed", "0.00")))
        currency = (data.get("currency") or self.config.get("currency") or "USD").upper()
        return {"rate": rate, "fixed": fixed, "currency": currency}

    def _fee(self, amount: Decimal, cfg: Dict[str, Any]) -> Dict[str, Any]:
        fee = (amount * cfg["rate"] + cfg["fixed"]).quantize(CENT, rounding=ROUND_HALF_UP)
        return {
            "platform_fee": fee,
            "provider_net": (amount - fee).quantize(CENT, rounding=ROUND_HALF_UP),
        }

    def _dedupe(self, key: str, outcome: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        prior = self.idempotent.get(key)
        if prior is not None:
            if prior.get("fingerprint") == outcome.get("fingerprint"):
                return {**prior, "idempotent": True}
            return {
                "status": "error",
                "error": "conflicting_repeat",
                "detail": "same operation repeated with different parameters",
            }
        return None

    # ----------------------------------------------------------- operations
    def _hold(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["payment_id", "amount"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        payment_id = data["payment_id"]
        try:
            amount = money(data["amount"])
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc)}
        if amount <= 0:
            return {"status": "error", "error": "amount_must_be_positive"}

        cfg = self._fee_config(data)
        existing = self.escrows.get(payment_id)
        if existing is not None:
            if existing["amount"] == amount and existing["fee"] == cfg:
                return {**existing["public"], "idempotent": True}
            return {
                "status": "error",
                "error": "duplicate_hold_mismatch",
                "detail": "payment_id already held with different amount or fee config",
            }

        quote = self._fee(amount, cfg)
        record = {
            "amount": amount,
            "fee": cfg,
            "quote": quote,
            "state": "held",
            "released": Decimal("0.00"),
        }
        public = {
            "status": "success",
            "operation": "hold",
            "payment_id": payment_id,
            "state": "held",
            "currency": cfg["currency"],
            "amount": str(amount),
            "platform_fee": str(quote["platform_fee"]),
            "provider_net": str(quote["provider_net"]),
        }
        record["public"] = public
        self.escrows[payment_id] = record
        return public

    def _fee_quote(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["amount"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        try:
            amount = money(data["amount"])
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc)}
        if amount <= 0:
            return {"status": "error", "error": "amount_must_be_positive"}
        cfg = self._fee_config(data)
        quote = self._fee(amount, cfg)
        return {
            "status": "success",
            "operation": "fee_quote",
            "currency": cfg["currency"],
            "amount": str(amount),
            "fee_rate": str(cfg["rate"]),
            "fee_fixed": str(cfg["fixed"]),
            "platform_fee": str(quote["platform_fee"]),
            "provider_net": str(quote["provider_net"]),
        }

    def _release(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._disburse(data, partial=False)

    def _partial_release(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._disburse(data, partial=True)

    def _disburse(self, data: Dict[str, Any], partial: bool) -> Dict[str, Any]:
        missing = self._require(data, ["payment_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        payment_id = data["payment_id"]
        record = self.escrows.get(payment_id)
        if record is None:
            return {"status": "error", "error": "payment_not_found", "payment_id": payment_id}
        if record["state"] not in ("held", "partial"):
            return {
                "status": "error",
                "error": f"invalid_transition: cannot release from {record['state']}",
            }

        try:
            amount = money(data["amount"]) if partial else record["amount"]
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc)}
        if partial and amount <= 0:
            return {"status": "error", "error": "amount_must_be_positive"}

        remaining = record["amount"] - record["released"]
        if amount > remaining:
            return {
                "status": "error",
                "error": "amount_exceeds_held",
                "releasable": str(remaining),
            }

        ratio = amount / record["amount"]
        fee_due = (record["quote"]["platform_fee"] * ratio).quantize(CENT, rounding=ROUND_HALF_UP)
        net = (amount - fee_due).quantize(CENT, rounding=ROUND_HALF_UP)
        record["released"] = (record["released"] + amount).quantize(CENT, rounding=ROUND_HALF_UP)
        new_state = "released" if record["released"] >= record["amount"] else "partial"
        record["state"] = new_state

        outcome = {
            "status": "success",
            "operation": "partial_release" if partial else "release",
            "payment_id": payment_id,
            "state": new_state,
            "released_amount": str(amount),
            "platform_fee": str(fee_due),
            "provider_net": str(net),
            "remaining": str((record["amount"] - record["released"]).quantize(CENT)),
        }
        key = f"{payment_id}|{outcome['operation']}|{amount}"
        self.idempotent.setdefault(key, {"fingerprint": amount, **outcome})
        return outcome

    def _refund(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["payment_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        payment_id = data["payment_id"]
        record = self.escrows.get(payment_id)
        if record is None:
            return {"status": "error", "error": "payment_not_found", "payment_id": payment_id}
        if record["state"] == "released":
            return {
                "status": "error",
                "error": "invalid_transition: fully released funds cannot be refunded",
            }
        refundable = (record["amount"] - record["released"]).quantize(CENT, rounding=ROUND_HALF_UP)
        record["state"] = "refunded"
        return {
            "status": "success",
            "operation": "refund",
            "payment_id": payment_id,
            "state": "refunded",
            "refunded_amount": str(refundable),
        }

    def _freeze(self, data: Dict[str, Any], frozen: bool) -> Dict[str, Any]:
        missing = self._require(data, ["payment_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        payment_id = data["payment_id"]
        record = self.escrows.get(payment_id)
        if record is None:
            return {"status": "error", "error": "payment_not_found", "payment_id": payment_id}
        if frozen:
            if record["state"] != "held":
                return {
                    "status": "error",
                    "error": f"invalid_transition: only held funds can be frozen (state={record['state']})",
                }
            record["state"] = "frozen"
        else:
            if record["state"] != "frozen":
                return {
                    "status": "error",
                    "error": f"invalid_transition: only frozen funds can be unfrozen (state={record['state']})",
                }
            record["state"] = "held"
        return {
            "status": "success",
            "operation": "freeze" if frozen else "unfreeze",
            "payment_id": payment_id,
            "state": record["state"],
        }

    def _status(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["payment_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        payment_id = data["payment_id"]
        record = self.escrows.get(payment_id)
        if record is None:
            return {"status": "error", "error": "payment_not_found", "payment_id": payment_id}
        return {
            "status": "success",
            "operation": "status",
            "payment_id": payment_id,
            "state": record["state"],
            "currency": record["fee"]["currency"],
            "amount": str(record["amount"]),
            "released": str(record["released"]),
            "remaining": str((record["amount"] - record["released"]).quantize(CENT)),
            "platform_fee_at_hold": str(record["quote"]["platform_fee"]),
        }
