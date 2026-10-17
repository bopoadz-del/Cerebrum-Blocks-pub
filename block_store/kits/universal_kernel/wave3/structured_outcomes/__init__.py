"""Neutral structured outcomes kit."""

from .code import (
    Outcome,
    OutcomeBuilder,
    OutcomeStatus,
    OutcomeValidationError,
    combine,
)

__all__ = [
    "Outcome",
    "OutcomeBuilder",
    "OutcomeStatus",
    "OutcomeValidationError",
    "combine",
]
