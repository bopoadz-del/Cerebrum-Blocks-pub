"""Neutral block-runner primitives.

A fail-closed command runner: only allow-listed commands are accepted, arguments
are validated against a simple schema and scanned for dangerous patterns, and
every execution is appended to the audit-evidence chain. Outcomes are modelled
with the structured_outcomes kit.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from block_store.kits.universal_kernel.wave1.audit_evidence import record as audit_record
from block_store.kits.universal_kernel.wave3.structured_outcomes import (
    Outcome,
    OutcomeBuilder,
    OutcomeStatus,
)


class UnsafeArgumentError(ValueError):
    """Raised when arguments contain unsafe patterns."""


@dataclass
class BlockEnvelope:
    """A request to execute a registered block/command."""

    command: str
    arguments: Dict[str, Any]
    principal: Dict[str, Any]
    scope: Dict[str, Any]


# Dangerous substrings that must not appear in string arguments.
_DANGEROUS_STRINGS = (
    "__import__",
    "eval(",
    "exec(",
    "compile(",
    "subprocess",
    "os.system",
)

# Import/module names that are forbidden in restricted (pure-function) handlers.
_RESTRICTED_FORBIDDEN = (
    "subprocess",
    "socket",
    "urllib",
    "requests",
    "httpx",
    "open(",
    "os.system",
    "os.path",
    "pathlib",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_safe_value(value: Any) -> bool:
    """Recursively scan a value for dangerous strings."""
    if isinstance(value, str):
        return not any(dangerous in value for dangerous in _DANGEROUS_STRINGS)
    if isinstance(value, list):
        return all(_is_safe_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            _is_safe_value(key) and _is_safe_value(val)
            for key, val in value.items()
        )
    return True


def _validate_type(value: Any, expected: str) -> bool:
    """Minimal primitive-type validator (no code execution)."""
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def _validate_schema(arguments: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    """Validate ``arguments`` against a simple per-key JSON schema."""
    errors: List[str] = []
    for key, spec in schema.items():
        if key not in arguments:
            errors.append(f"missing required argument '{key}'")
            continue
        expected_type = spec.get("type") if isinstance(spec, dict) else spec
        if expected_type and not _validate_type(arguments[key], expected_type):
            errors.append(f"argument '{key}' must be of type {expected_type}")
    return errors


def _safe_error_message(error: Exception) -> str:
    """Return a safe, non-leaking error message."""
    return f"handler error: {type(error).__name__}"


class BlockRunner:
    """Allow-list based command runner with schema validation and audit."""

    def __init__(
        self,
        allowlist: List[str],
        registry: Dict[str, Callable],
        schemas: Optional[Dict[str, Dict[str, Any]]] = None,
        audit_principal_id: str = "block_runner",
    ) -> None:
        self.allowlist: Set[str] = set(allowlist)
        self.registry = dict(registry)
        self.schemas = dict(schemas) if schemas else {}
        self.audit_principal_id = audit_principal_id

    def _audit(
        self,
        envelope: BlockEnvelope,
        outcome_status: str,
        payload: Dict[str, Any],
    ) -> None:
        audit_record(
            event_type="block_executed",
            principal=envelope.principal,
            scope=envelope.scope,
            action=envelope.command,
            outcome=outcome_status,
            payload=payload,
        )

    def _check_handler_security(self, handler: Callable) -> Optional[str]:
        """Return an error string if the handler fails security checks."""
        return None

    def _build_failure(
        self,
        envelope: BlockEnvelope,
        error_code: str,
        error_message: str,
        honesty: str = "direct",
    ) -> Outcome:
        self._audit(
            envelope,
            OutcomeStatus.failure.value,
            {
                "error_code": error_code,
                "error_message": error_message,
                "arguments": envelope.arguments,
            },
        )
        return Outcome(
            status=OutcomeStatus.failure,
            data={"error_code": error_code, "error_message": error_message},
            evidence=[],
            honesty=honesty,
        )

    def run(self, envelope: BlockEnvelope) -> Outcome:
        """Run an envelope through the allow-list, schema, handler pipeline."""
        if envelope.command not in self.allowlist:
            return self._build_failure(
                envelope,
                "command_not_allowed",
                f"command '{envelope.command}' is not in the allowlist",
            )

        if not _is_safe_value(envelope.arguments):
            return self._build_failure(
                envelope,
                "unsafe_arguments",
                "arguments contain unsafe patterns",
            )

        schema = self.schemas.get(envelope.command)
        if schema:
            schema_errors = _validate_schema(envelope.arguments, schema)
            if schema_errors:
                return self._build_failure(
                    envelope,
                    "schema_validation_error",
                    "; ".join(schema_errors),
                )

        handler = self.registry.get(envelope.command)
        if handler is None:
            return self._build_failure(
                envelope,
                "handler_not_found",
                f"no handler registered for '{envelope.command}'",
            )

        security_error = self._check_handler_security(handler)
        if security_error:
            return self._build_failure(
                envelope,
                "handler_security_error",
                security_error,
            )

        try:
            result = handler(envelope.arguments)
        except Exception as exc:  # noqa: BLE001 - deliberately broad; no leakage
            return self._build_failure(
                envelope,
                "handler_exception",
                _safe_error_message(exc),
            )

        if not isinstance(result, dict):
            return self._build_failure(
                envelope,
                "invalid_handler_result",
                "handler must return a dict",
            )

        outcome = Outcome(
            status=OutcomeStatus.success,
            data=result,
            evidence=[
                {
                    "event_type": "block_executed",
                    "command": envelope.command,
                    "timestamp": _now(),
                    "audit_principal": self.audit_principal_id,
                }
            ],
            honesty="direct",
        )
        self._audit(
            envelope,
            OutcomeStatus.success.value,
            {
                "arguments": envelope.arguments,
                "result_keys": list(result.keys()),
            },
        )
        return outcome


class RestrictedRunner(BlockRunner):
    """BlockRunner that further restricts handlers to pure functions.

    Handlers are inspected via ``inspect.getsource``; any subprocess, network,
    or file-import usage causes the run to fail closed.
    """

    def _check_handler_security(self, handler: Callable) -> Optional[str]:
        try:
            source = inspect.getsource(handler)
        except (OSError, TypeError):
            # Fail closed: if we cannot verify purity, deny the handler.
            return "unable to verify handler source"
        lowered = source.lower()
        for forbidden in _RESTRICTED_FORBIDDEN:
            if forbidden in lowered:
                return f"handler uses forbidden capability: {forbidden}"
        return None
