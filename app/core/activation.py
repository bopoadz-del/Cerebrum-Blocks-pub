"""Activation flags â€” features ship dormant; activation is explicit and frozen.

General-case fix for the no-LLM-set-still-green / zero-artifact-still-green
failure class: a feature that changes behavior must sit behind a named
activation flag whose default is OFF, whose off path is a byte-for-byte
noop of the pre-feature behavior, and whose value is frozen at first read
(config cannot toggle mid-run). Every gated feature carries the mandatory
test pair: ``test_flag_off_is_noop`` + ``test_flag_on_changes_behavior``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger("cerebrum.activation")

TRUTHY = {"1", "true", "yes", "on"}
FALSEY = {"0", "false", "no", "off"}


class ActivationError(ValueError):
    """Named activation refusal. Never a bare boolean."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, Any]:
        return {"refused": True, "code": self.code, "message": self.message}


class ActivationFlag:
    """Named env-gated switch, default OFF, frozen at first read.

    An unrecognized non-empty value is a loud error, never a guess: a
    typo must not silently ship the dormant path.
    """

    def __init__(self, name: str, env_var: str, default: bool = False) -> None:
        self.name = name
        self.env_var = env_var
        self.default = default
        self._frozen: Optional[bool] = None

    @property
    def enabled(self) -> bool:
        if self._frozen is None:
            self._frozen = self._resolve()
        return self._frozen

    def _resolve(self) -> bool:
        raw = (os.getenv(self.env_var) or "").strip().lower()
        if not raw:
            return self.default
        if raw in TRUTHY:
            return True
        if raw in FALSEY:
            return False
        raise ActivationError(
            "activation_flag_invalid_value",
            f"{self.env_var}={raw!r} is not a valid activation value "
            "(use 1/true/yes/on or 0/false/no/off); refusing to guess",
        )


class ActivationAdapter:
    """Dormant-when-off adapter. The off path is a byte-for-byte noop."""

    def __init__(self, flag: ActivationFlag, *, when_on: Callable[..., Any]) -> None:
        self.flag = flag
        self._when_on = when_on

    def apply(self, *args: Any, **kwargs: Any) -> Any:
        """Run the feature when enabled; do nothing (return None) when off."""
        if not self.flag.enabled:
            return None
        return self._when_on(*args, **kwargs)

    def require(self) -> Callable[..., Any]:
        """Return the active callable; fail loud with a named reason when off."""
        if not self.flag.enabled:
            raise ActivationError(
                "activation_flag_off",
                f"feature {self.flag.name!r} requires {self.flag.env_var}=1; "
                "it is dormant in this process",
            )
        return self._when_on


# -- first adoption: execution audit note on the universal entry path --------

_BLOCK_EXECUTION_AUDIT = ActivationFlag(
    "block_execution_audit", "BLOCK_EXECUTION_AUDIT_ENABLED"
)


def _emit_execution_note(block_name: str, request_id: str, status: str) -> None:
    logger.info(
        "block execution audit: block=%s request_id=%s status=%s",
        block_name,
        request_id,
        status,
    )


_AUDIT_ADAPTER = ActivationAdapter(
    _BLOCK_EXECUTION_AUDIT, when_on=_emit_execution_note
)


def emit_block_execution_note(block_name: str, request_id: str, status: str) -> Any:
    """Gated execution-audit note. OFF = byte-for-byte noop (returns None)."""
    return _AUDIT_ADAPTER.apply(block_name, request_id, status)
