"""Shared HTTP error classification for router -> block error translation.

Routers consume blocks. A block failure maps to an HTTP status by its TYPED
kind, never by the words in its message:

    503  = service unavailable -- a required configuration or credential is
           missing, or the network / provider is down. The platform is fine;
           an integration is not reachable. ``error_kind == "unavailable"``.
    422  = unprocessable entity -- a problem the caller can fix (wrong field,
           malformed file, bad value). ``error_kind == "input"`` (the default).

The kind comes from the cause, where the cause is known:

* an exception carries it -- ``BlockUnavailable`` (config / credentials /
  provider) and the standard library's connection, timeout, DNS and TLS
  errors are ``unavailable``, found anywhere in the cause chain (so any HTTP
  client's wrapper of them is too); any exception may also set an
  ``error_kind`` attribute itself;
* a block envelope carries it -- ``{"status": "error", "error": ...,
  "error_kind": ...}``, built with ``unavailable()`` / ``error_from()``.

A bare message string carries no kind and classifies as ``input``.
"""

from __future__ import annotations

import socket
import ssl
from typing import Any, Dict, Mapping

UNAVAILABLE = "unavailable"
INPUT = "input"
ERROR_KINDS = (UNAVAILABLE, INPUT)


class BlockUnavailable(RuntimeError):
    """A required configuration, credential or provider is missing or down."""

    error_kind = UNAVAILABLE


#: The OS-level failures that mean "the provider cannot be reached". Every
#: HTTP client library raises its own exception ``from`` one of these, so the
#: cause chain is searched and no client library is named or imported here.
_UNAVAILABLE_CAUSES = (BlockUnavailable, ConnectionError, TimeoutError, socket.gaierror, ssl.SSLError)


def _causes(exc: BaseException):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def error_kind(exc: BaseException) -> str:
    """The kind of a failure: an exception's own declared kind, else
    ``unavailable`` when it -- or anything it was raised from -- is a
    connection, timeout, DNS or TLS failure, else ``input``."""
    declared = getattr(exc, "error_kind", None)
    if declared in ERROR_KINDS:
        return declared
    return UNAVAILABLE if any(isinstance(e, _UNAVAILABLE_CAUSES) for e in _causes(exc)) else INPUT


def mark_unavailable(exc: BaseException) -> BaseException:
    """Mark an exception of any type as an unavailable-integration failure,
    keeping its type (so ``except ValueError`` callers are unchanged)."""
    exc.error_kind = UNAVAILABLE  # type: ignore[attr-defined]
    return exc


def unavailable(message: str, **extra: Any) -> Dict[str, Any]:
    """An error envelope for a missing configuration / credential / provider."""
    return {"status": "error", "error": message, "error_kind": UNAVAILABLE, **extra}


def error_from(exc: BaseException, **extra: Any) -> Dict[str, Any]:
    """An error envelope that keeps the exception's kind."""
    return {"status": "error", "error": str(exc), "error_kind": error_kind(exc), **extra}


def _kind_of(outcome: Any) -> str:
    if isinstance(outcome, BaseException):
        return error_kind(outcome)
    if isinstance(outcome, Mapping):
        kind = outcome.get("error_kind")
        if kind in ERROR_KINDS:
            return kind
        inner = outcome.get("result")
        if isinstance(inner, Mapping) and inner.get("error_kind") in ERROR_KINDS:
            return inner["error_kind"]
    return INPUT


def classify_block_error(outcome: Any) -> int:
    """HTTP status for a block failure: 503 when it is ``unavailable``, else 422.

    ``outcome`` is the exception, or the block's result / envelope. A plain
    message string carries no kind and is treated as an input problem.
    """
    return 503 if _kind_of(outcome) == UNAVAILABLE else 422
