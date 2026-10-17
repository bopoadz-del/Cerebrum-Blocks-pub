"""Safe metric calculation helpers for domain block calculators.

Light-weight input validation and safe division utilities used by
``TypedBlock`` subclasses so metric methods fail loudly on bad inputs
instead of returning silent ``inf``/``NaN`` values.
"""

from datetime import date, datetime
from typing import Any, Union


Number = Union[int, float]


def _is_positive_number(x: Any) -> bool:
    """Return True if *x* is a positive int or float."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0


def _safe_divide(numerator: Any, denominator: Any, scale: Number = 1.0) -> float:
    """Return ``(numerator / denominator) * scale`` with validation.

    Args:
        numerator: Dividend; must be a number.
        denominator: Divisor; must be a positive number.
        scale: Factor applied after division (e.g. 100 for percentages).

    Raises:
        ValueError: If *denominator* is not a positive number or if
            *numerator* is not a number.
    """
    if not isinstance(numerator, (int, float)) or isinstance(numerator, bool):
        raise ValueError(f"Numerator must be a number, got {type(numerator).__name__}")
    if not _is_positive_number(denominator):
        raise ValueError(f"Denominator must be a positive number, got {denominator!r}")
    if not isinstance(scale, (int, float)) or isinstance(scale, bool):
        raise ValueError(f"Scale must be a number, got {type(scale).__name__}")
    return (numerator / denominator) * scale


def _days_between(start: Any, end: Any) -> int:
    """Return ``(end - start).days`` with validation.

    Args:
        start: Start date/datetime.
        end: End date/datetime.

    Raises:
        ValueError: If either argument is not a ``date``/``datetime`` or
            if *start* is after *end*.
    """
    if not isinstance(start, (date, datetime)):
        raise ValueError(f"Start must be a date or datetime, got {type(start).__name__}")
    if not isinstance(end, (date, datetime)):
        raise ValueError(f"End must be a date or datetime, got {type(end).__name__}")
    if start > end:
        raise ValueError(f"Start date {start} is after end date {end}")
    return (end - start).days
