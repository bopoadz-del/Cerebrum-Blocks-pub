"""Neutral structured outcome primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class OutcomeStatus(str, Enum):
    """Closed set of terminal outcome statuses."""

    success = "success"
    failure = "failure"
    partial = "partial"
    insufficient = "insufficient"


class OutcomeValidationError(ValueError):
    """Raised when an outcome fails validation."""


@dataclass
class Outcome:
    """A single structured outcome with evidence and an honesty label."""

    status: OutcomeStatus
    data: Dict[str, Any] = field(default_factory=dict)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    honesty: str = "direct"

    def __post_init__(self) -> None:
        if not isinstance(self.status, OutcomeStatus):
            raise OutcomeValidationError("status must be an OutcomeStatus")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "data": self.data,
            "evidence": self.evidence,
            "honesty": self.honesty,
        }


class OutcomeBuilder:
    """Collects outputs and returns a validated outcome dict."""

    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}
        self._evidence: List[Dict[str, Any]] = []
        self._warnings: List[str] = []

    def add(self, key: str, value: Any) -> "OutcomeBuilder":
        """Add a key/value to the outcome data."""
        self._data[key] = value
        return self

    def add_evidence(self, evidence: Dict[str, Any]) -> "OutcomeBuilder":
        """Attach evidence to the outcome."""
        self._evidence.append(evidence)
        return self

    def warn(self, message: str) -> "OutcomeBuilder":
        """Add a warning note."""
        self._warnings.append(message)
        return self

    def build(
        self,
        status: OutcomeStatus = OutcomeStatus.success,
        honesty: str = "direct",
    ) -> Dict[str, Any]:
        """Return a validated outcome dict."""
        outcome = Outcome(
            status=status,
            data=self._data,
            evidence=self._evidence,
            honesty=honesty,
        )
        result = outcome.to_dict()
        if self._warnings:
            result["warnings"] = list(self._warnings)
        return result


_WORST_ORDER = [
    OutcomeStatus.success,
    OutcomeStatus.partial,
    OutcomeStatus.insufficient,
    OutcomeStatus.failure,
]


def combine(outcomes: List[Outcome]) -> Dict[str, Any]:
    """Aggregate multiple outcomes; the worst status wins.

    Raises:
        OutcomeValidationError: When the input list is empty.
    """
    if not outcomes:
        raise OutcomeValidationError("cannot combine empty outcomes list")

    worst = max(outcomes, key=lambda o: _WORST_ORDER.index(o.status))
    merged_data: Dict[str, Any] = {}
    evidence: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for outcome in outcomes:
        merged_data.update(outcome.data)
        evidence.extend(outcome.evidence)
        if outcome.honesty != "direct":
            warnings.append(f"outcome used honesty={outcome.honesty}")

    result = Outcome(
        status=worst.status,
        data=merged_data,
        evidence=evidence,
        honesty="combined",
    ).to_dict()
    if warnings:
        result["warnings"] = warnings
    return result
