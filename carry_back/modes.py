"""Operating modes for the Carry-Back Agent."""

from __future__ import annotations

from enum import Enum


class Mode(str, Enum):
    """dry-run = plan only; propose = write artifacts/branch; live = gated."""

    DRY_RUN = "dry-run"
    PROPOSE = "propose"
    LIVE = "live"


def parse_mode(value: str) -> Mode:
    normalized = (value or "").strip().lower().replace("_", "-")
    try:
        return Mode(normalized)
    except ValueError as exc:
        allowed = ", ".join(m.value for m in Mode)
        raise ValueError(f"Unknown mode {value!r}; expected one of: {allowed}") from exc
