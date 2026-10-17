"""Fail-Closed Audit Middleware + Principal Auth â€” ported from
<private-repo> ``api/audit_middleware.py`` + ``api/auth.py``.

Ported exactly:
- Principal resolution from a verified bearer token only
  (hmac.compare_digest against configured operator/reviewer tokens).
  Client-supplied x-actor / x-role headers are NEVER read.
- The pure-ASGI AuditMiddleware: public paths (/health, /assets) bypass
  audit; authenticated mutating responses are HELD until the audit row is
  persisted; a persist failure on an otherwise-2xx mutating response is
  surfaced as 503 instead of a silent success (fail_closed).
- persist_audit_event: the block's ledger is in-process (honest: this is
  not the donor's sqlite sessionmaker). The persist callable is injectable
  so a failing store is observable; it raises rather than returning.
- Unconfigured tokens refuse authentication (donor's
  AuthTokensNotConfigured contract); missing / unknown bearer tokens
  refuse with the donor's 401/403 semantics.
"""
from __future__ import annotations

import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "audit_fail_closed", "status": status, "result": result, "error": error, "detail": detail}


ANONYMOUS_ACTOR = "anonymous"
ANONYMOUS_ROLE = "unknown"


@dataclass(frozen=True)
class Principal:
    actor: str
    role: str


ANONYMOUS = Principal(actor=ANONYMOUS_ACTOR, role=ANONYMOUS_ROLE)


def _token_eq(provided: str, expected: str) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def principal_from_token(token: Optional[str], operator_token: str, reviewer_token: str) -> Optional[Principal]:
    """Resolve a bearer token to a Principal. None if missing, unknown, or tokens unset."""
    if not operator_token or not reviewer_token or not token:
        return None
    token = token.strip()
    if _token_eq(token, operator_token.strip()):
        return Principal("operator", "operator")
    if _token_eq(token, reviewer_token.strip()):
        return Principal("reviewer", "reviewer")
    return None


def principal_from_authorization(authorization: Optional[str], operator_token: str, reviewer_token: str) -> Principal:
    """Same resolution as HTTPBearer auth. Never reads x-actor / x-role headers."""
    if not authorization:
        return ANONYMOUS
    scheme, sep, token = authorization.partition(" ")
    if not sep or scheme.lower() != "bearer":
        return ANONYMOUS
    return principal_from_token(token.strip(), operator_token, reviewer_token) or ANONYMOUS


PUBLIC_PREFIXES = ("/health", "/assets")
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
AUDIT_FAIL_DETAIL = "audit persistence failed"


def is_public_audit_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def _header_map(scope: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in scope.get("headers") or []:
        name = key.decode("latin-1").lower()
        if name not in out:
            out[name] = value.decode("latin-1")
    return out


class AuditMiddleware:
    def __init__(self, app, *, persist: Callable[..., None], resolve: Callable[[Optional[str]], Principal]):
        self.app = app
        self._persist = persist
        self._resolve = resolve

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        method = scope.get("method") or ""
        if is_public_audit_path(path):
            await self.app(scope, receive, send)
            return

        headers = _header_map(scope)
        principal = self._resolve(headers.get("authorization"))
        actor = principal.actor
        role = principal.role
        authenticated = role != ANONYMOUS_ROLE
        hold = authenticated and method.upper() in MUTATING_METHODS

        status_code = 500
        start_message: Optional[Dict[str, Any]] = None
        body_messages: List[Dict[str, Any]] = []

        async def send_wrapper(message: Dict[str, Any]) -> None:
            nonlocal status_code, start_message
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                if hold:
                    start_message = message
                    return
            elif hold and message["type"] == "http.response.body":
                body_messages.append(message)
                return
            await send(message)

        await self.app(scope, receive, send_wrapper)

        persist_ok = True
        try:
            self._persist(
                actor=actor,
                role=role,
                method=method,
                path=path,
                status_code=status_code,
            )
        except Exception as exc:  # noqa: BLE001 - the donor logs and fails closed
            persist_ok = False
            self._persist_error = str(exc)

        if not hold:
            return

        fail_closed = persist_ok is False and 200 <= status_code < 400
        if fail_closed:
            body = json.dumps({"detail": AUDIT_FAIL_DETAIL}).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        if start_message is not None:
            await send(start_message)
            for message in body_messages:
                await send(message)
            if not body_messages:
                await send({"type": "http.response.body", "body": b""})


class AuditFailClosedBlock(UniversalBlock):
    """Fail-closed audit middleware + principal auth ported from <private-repo>."""

    name = "audit_fail_closed"
    version = "1.0.0"
    description = (
        "Fail-closed ASGI audit middleware + principal auth ported from "
        "<private-repo> api/audit_middleware.py + api/auth.py (real): "
        "actor attribution comes only from a verified bearer token "
        "(hmac.compare_digest), never from client x-actor/x-role headers; "
        "authenticated mutating responses are held until the audit row "
        "persists and a persist failure surfaces 503 instead of a silent "
        "2xx. The audit ledger is in-process (the donor's sqlite "
        "sessionmaker is not ported); unconfigured tokens refuse "
        "authentication."
    )
    layer = 1
    tags = ["security", "audit", "asgi", "middleware", "fail-closed", "hotelops"]
    requires = []

    default_config = {"operator_token": "", "reviewer_token": ""}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "principal", "authorization": "Bearer op-token"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._ledger: List[Dict[str, Any]] = []

    def _operator_token(self) -> str:
        return str(self.config.get("operator_token") or "")

    def _reviewer_token(self) -> str:
        return str(self.config.get("reviewer_token") or "")

    def tokens_configured(self) -> bool:
        return bool(self._operator_token().strip()) and bool(self._reviewer_token().strip())

    def _resolve(self, authorization: Optional[str]) -> Principal:
        return principal_from_authorization(authorization, self._operator_token(), self._reviewer_token())

    def _persist(self, *, actor: str, role: str, method: str, path: str, status_code: int, detail: str = "") -> None:
        row = {
            "id": len(self._ledger) + 1,
            "ts": time.time(),
            "actor": actor,
            "role": role,
            "method": method,
            "path": path,
            "status_code": status_code,
            "detail": detail,
        }
        self._ledger.append(row)

    def make_middleware(self, app, *, persist: Optional[Callable[..., None]] = None, resolve: Optional[Callable[[Optional[str]], Principal]] = None):
        return AuditMiddleware(
            app,
            persist=persist or self._persist,
            resolve=resolve or self._resolve,
        )

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "principal")).lower()
        try:
            if action == "principal":
                principal = self._resolve(payload.get("authorization"))
                return _envelope("ok", {"actor": principal.actor, "role": principal.role})
            if action == "require_principal":
                if not self.tokens_configured():
                    return _envelope("refused", error="auth_tokens_not_configured", detail={"message": "auth tokens are not configured"})
                authorization = payload.get("authorization")
                if not authorization:
                    return _envelope("refused", error="missing_bearer_token", detail={"message": "missing bearer token"})
                principal = self._resolve(authorization)
                if principal.role == ANONYMOUS_ROLE:
                    return _envelope("refused", error="unknown_token", detail={"message": "unknown token"})
                return _envelope("ok", {"actor": principal.actor, "role": principal.role})
            if action == "require_operator":
                principal = self._resolve(payload.get("authorization"))
                if principal.role != "operator":
                    return _envelope("refused", error="operator_role_required", detail={"message": "operator role required"})
                return _envelope("ok", {"actor": principal.actor, "role": principal.role})
            if action == "record":
                if payload.get("persist_error"):
                    raise RuntimeError("injected persist failure")
                self._persist(
                    actor=str(payload.get("actor") or ANONYMOUS_ACTOR),
                    role=str(payload.get("role") or ANONYMOUS_ROLE),
                    method=str(payload.get("method") or ""),
                    path=str(payload.get("path") or ""),
                    status_code=int(payload.get("status_code") or 0),
                    detail=str(payload.get("detail") or ""),
                )
                return _envelope("ok", {"recorded": len(self._ledger)})
            if action == "ledger":
                return _envelope("ok", {"rows": list(self._ledger)})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["principal", "require_principal", "require_operator", "record", "ledger"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            if action == "record":
                return _envelope("failed", error=str(exc), detail={"action": action})
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
