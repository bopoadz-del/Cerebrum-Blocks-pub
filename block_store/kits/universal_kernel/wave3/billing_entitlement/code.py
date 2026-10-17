"""Neutral entitlement / quota primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class EntitlementExceeded(Exception):
    """Raised when an entitlement quota is exceeded."""


class EntitlementError(ValueError):
    """Raised for invalid entitlement operations."""


@dataclass
class Entitlement:
    """A single principal/feature entitlement within a time window."""

    principal_id: str
    feature: str
    quota: int
    used: int = 0
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.quota < 0:
            raise EntitlementError("quota cannot be negative")
        if self.used < 0:
            raise EntitlementError("used cannot be negative")
        if (
            self.window_start
            and self.window_end
            and self.window_start >= self.window_end
        ):
            raise EntitlementError("window_start must be before window_end")

    def remaining(self) -> int:
        """Remaining quota for this entitlement."""
        return max(0, self.quota - self.used)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "principal_id": self.principal_id,
            "feature": self.feature,
            "quota": self.quota,
            "used": self.used,
            "window_start": self.window_start.isoformat()
            if self.window_start
            else None,
            "window_end": self.window_end.isoformat()
            if self.window_end
            else None,
        }


class EntitlementLedger:
    """In-memory entitlement ledger with an optional persistence stub."""

    def __init__(self, persistence: Optional[Any] = None) -> None:
        self._store: Dict[str, Entitlement] = {}
        self._persistence = persistence

    @staticmethod
    def _key(principal_id: str, feature: str) -> str:
        return f"{principal_id}:{feature}"

    def set(self, entitlement: Entitlement) -> None:
        """Store or overwrite an entitlement."""
        self._store[self._key(entitlement.principal_id, entitlement.feature)] = entitlement
        if self._persistence is not None:
            self._persistence.save(entitlement)

    def get(self, principal_id: str, feature: str) -> Optional[Entitlement]:
        """Retrieve an entitlement, consulting persistence if configured."""
        key = self._key(principal_id, feature)
        entitlement = self._store.get(key)
        if entitlement is None and self._persistence is not None:
            entitlement = self._persistence.load(principal_id, feature)
            if entitlement is not None:
                self._store[key] = entitlement
        return entitlement

    def check_entitlement(
        self,
        principal_id: str,
        feature: str,
        required: int = 1,
    ) -> Dict[str, Any]:
        """Check whether a principal may use a feature.

        Returns:
            Dict with ``allowed``, ``remaining``, and ``reason``.
        """
        if required < 0:
            raise EntitlementError("required cannot be negative")

        entitlement = self.get(principal_id, feature)
        if entitlement is None:
            return {
                "allowed": False,
                "remaining": 0,
                "reason": "entitlement not found",
            }

        now = datetime.now(timezone.utc)
        if entitlement.window_end and now > entitlement.window_end:
            return {
                "allowed": False,
                "remaining": 0,
                "reason": "entitlement window expired",
            }

        remaining = entitlement.remaining()
        allowed = remaining >= required
        return {
            "allowed": allowed,
            "remaining": remaining,
            "reason": None if allowed else "quota exceeded",
        }

    def record_usage(
        self,
        principal_id: str,
        feature: str,
        amount: int = 1,
    ) -> Dict[str, Any]:
        """Record usage against an entitlement."""
        if amount < 0:
            raise EntitlementError("amount cannot be negative")

        entitlement = self.get(principal_id, feature)
        if entitlement is None:
            raise EntitlementExceeded("entitlement not found")

        result = self.check_entitlement(principal_id, feature, amount)
        if not result["allowed"]:
            raise EntitlementExceeded(result["reason"] or "quota exceeded")

        entitlement.used += amount
        if self._persistence is not None:
            self._persistence.save(entitlement)

        return {"recorded": amount, "remaining": entitlement.remaining()}

    def require_entitled(
        self,
        principal_id: str,
        feature: str,
        required: int = 1,
    ) -> None:
        """Raise EntitlementExceeded if the principal is not entitled."""
        result = self.check_entitlement(principal_id, feature, required)
        if not result["allowed"]:
            raise EntitlementExceeded(result["reason"] or "entitlement denied")
