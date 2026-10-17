"""Tier × block access control for the public block surface.

The audit found that a single API key reaches every registered block via
`/v1/execute`, `/chain`, and `/mcp`. Blocks like `code`, `sandbox`,
`formula_executor`, `secrets`, `database`, `web`, `webhook`,
`file_hasher`, `storage`, `email`, and `billing` are RCE / SSRF / FS
traversal / vault-read primitives. Combined with the public-tier API
key shipped in the SPA bundle, that's a server-compromise vector.

This module defines the set of blocks that require the `unlimited` tier
(master / dev keys only) and the helper `enforce_block_access` used by
the route handlers.

Override at runtime by setting `CEREBRUM_RESTRICTED_BLOCKS` to a
comma-separated list. To open a normally-restricted block to standard
tier, prefix with `-`:

    CEREBRUM_RESTRICTED_BLOCKS=-email,my_custom_dangerous_block
"""

from __future__ import annotations

import contextvars
import logging
import os
from typing import Any, Dict, Optional, Set

from fastapi import HTTPException

logger = logging.getLogger(__name__)


# The tier of the request currently being served, set at the auth boundary
# (require_api_key) and read at block RESOLUTION.
_current_auth: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "cerebrum_current_auth", default=None
)

# True while an HTTP request is being served. Set by RequestContextMiddleware
# (a raw ASGI middleware, so the contextvar propagates into the endpoint and its
# internal block resolutions — BaseHTTPMiddleware runs the endpoint in a
# separate task and would break propagation). This is what lets the resolution
# gate FAIL CLOSED: an in-flight request whose tier is unknown is denied, while
# genuine no-request contexts (boot, registry validation, warm-up) stay
# permissive.
_in_request: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "cerebrum_in_request", default=False
)


def set_current_auth(auth: Optional[Dict[str, Any]]) -> None:
    """Record the auth dict of the in-flight request (called by require_api_key)."""
    _current_auth.set(auth)


def get_current_auth() -> Optional[Dict[str, Any]]:
    """Return the in-flight request's auth dict, or None outside a request."""
    return _current_auth.get()


def begin_request_context() -> None:
    """Mark the start of an in-flight HTTP request and clear any stale auth.

    Called by RequestContextMiddleware at the top of every HTTP request so each
    request starts with a known-clean context (in-flight, no tier yet); the auth
    boundary then fills in the real tier.
    """
    _current_auth.set(None)
    _in_request.set(True)


def in_request_context() -> bool:
    """True when an HTTP request is currently being served."""
    return _in_request.get()


# Blocks that the audit identified as critical RCE / SSRF / vault / FS
# primitives. Standard-tier keys (including the SPA-shipped public key)
# get HTTP 403 when invoking any of these via /v1/execute, /chain, or
# /mcp. Unlimited tier (master, dev) bypasses the restriction.
_DEFAULT_RESTRICTED_BLOCKS: Set[str] = {
    # Code execution → arbitrary subprocess with full host environment.
    "code",
    "sandbox",
    "formula_executor",
    # Vault read.
    "secrets",
    # Raw SQL with no parameterisation guarantees.
    "database",
    # Outbound HTTP — no SSRF guard, response body returned to caller.
    "web",
    "webhook",
    # File-system primitives that lack the local_drive sandbox.
    "file_hasher",
    "storage",
    # Mail relay.
    "email",
    # State mutation (billing usage, plan upgrades).
    "billing",
}


def _parse_env_overrides() -> Set[str]:
    """Apply CEREBRUM_RESTRICTED_BLOCKS overrides on top of the default set.

    Each entry is a block name. Prefix with `-` to remove an existing entry.
    Whitespace is stripped. Empty entries are ignored.
    """
    raw = os.getenv("CEREBRUM_RESTRICTED_BLOCKS", "").strip()
    restricted: Set[str] = set(_DEFAULT_RESTRICTED_BLOCKS)
    if not raw:
        return restricted
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if token.startswith("-"):
            restricted.discard(token[1:])
        else:
            restricted.add(token)
    return restricted


# Resolve once at import time. Reload would require a process restart,
# which matches the operational model for changing security policy.
RESTRICTED_BLOCKS: Set[str] = _parse_env_overrides()
logger.info(
    "security: %d restricted block(s) — unlimited-tier only: %s",
    len(RESTRICTED_BLOCKS),
    ", ".join(sorted(RESTRICTED_BLOCKS)) or "(none)",
)


def is_restricted(block_name: str) -> bool:
    return block_name in RESTRICTED_BLOCKS


def enforce_restricted_resolution(block_name: str) -> None:
    """Choke-point gate applied at block RESOLUTION (instance creation).

    The audit found ``enforce_block_access`` was only called by ``/v1/execute``
    and ``/chain``. Every other dispatch path — ``/swarm/execute``,
    ``/workflow/run``, ``/notify``, ``async_processor``, ``jetson_gateway`` —
    reaches blocks by name via ``get_block_instance`` / ``_create_block_instance``
    with no tier check, so a standard-tier key could reach the ``database``
    (raw-SQL), ``code``/``sandbox`` (RCE), ``secrets`` (vault) primitives.

    This gate runs wherever a block is instantiated and FAILS CLOSED:
      - ``tier == "unlimited"`` → allowed.
      - Any other tier while a request is in flight — including an *unknown*
        tier (the contextvar was never set to a real auth) → DENIED. An
        unauthenticated or mis-wired route must not reach a privileged
        primitive just because it skipped the auth dependency.
      - No request context at all (boot, registry validation, warm-up) →
        permissive, so start-up and internal resolution never break.
    """
    if block_name not in RESTRICTED_BLOCKS:
        return
    tier = (_current_auth.get() or {}).get("tier")
    if tier == "unlimited":
        return
    if not in_request_context():
        return  # boot / registry validation / system warm-up — no request
    # In-flight request without unlimited tier (unknown tier included) — deny.
    user = (_current_auth.get() or {}).get("user", "?")
    logger.warning(
        "security: blocked resolution of restricted block '%s' (tier=%s, user=%s) "
        "— dispatch-path attempt to reach a privileged primitive",
        block_name, tier or "unknown", user,
    )
    raise HTTPException(
        status_code=403,
        detail=(
            f"Block '{block_name}' is restricted to unlimited-tier keys. "
            f"Your tier: {tier or 'unknown'}."
        ),
    )


def enforce_block_access(block_name: str, auth: Dict[str, Any]) -> None:
    """Raise HTTPException(403) if `auth` lacks access to `block_name`.

    The check is permissive by default: only blocks in `RESTRICTED_BLOCKS`
    require `tier == "unlimited"`. Everything else is reachable by any
    valid API key.

    Call this AFTER `require_api_key` in the route handler — `auth` is
    the dict it returns.
    """
    if block_name not in RESTRICTED_BLOCKS:
        return
    tier = (auth or {}).get("tier")
    if tier == "unlimited":
        return
    user = (auth or {}).get("user", "?")
    logger.warning(
        "security: blocked %s (tier=%s) from invoking restricted block '%s'",
        user, tier, block_name,
    )
    raise HTTPException(
        status_code=403,
        detail=(
            f"Block '{block_name}' is restricted to unlimited-tier keys. "
            f"Your tier: {tier or 'unknown'}."
        ),
    )


# ── /mcp gate ─────────────────────────────────────────────────────────────
# /mcp exposes BLOCK_REGISTRY entries as MCP tools, including the
# restricted set. Without authentication on the SSE transport, anyone on
# the public internet has RCE. We require Bearer auth + tier=unlimited
# by default; override via CEREBRUM_MCP_REQUIRED_TIER (e.g. "standard"
# if you need to broaden the surface) or CEREBRUM_MCP_DISABLE_AUTH=1
# (for local stdio testing only — never in production).

_MCP_REQUIRED_TIER = os.getenv("CEREBRUM_MCP_REQUIRED_TIER", "unlimited").strip().lower()
_MCP_DISABLE_AUTH = os.getenv("CEREBRUM_MCP_DISABLE_AUTH", "").strip().lower() in (
    "1", "true", "yes",
)


class RequestContextMiddleware:
    """Raw ASGI middleware that marks the in-flight request context.

    Runs the downstream app in the SAME task, so the contextvars it sets
    (``_in_request`` / cleared ``_current_auth``) propagate into the endpoint,
    its dependencies, and any block resolution they trigger. A
    ``BaseHTTPMiddleware`` would run the endpoint in a separate task and the
    propagation would be lost — which is why this is a plain ASGI class added
    via ``app.add_middleware(RequestContextMiddleware)``.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            begin_request_context()
        await self.app(scope, receive, send)


def _send_status_only(status: int, message: str):
    """Build an ASGI send-callable closure that emits a JSON error response."""
    body = (
        '{"error":"' + message.replace('"', "\\\"") + '"}'
    ).encode("utf-8")

    async def _send(send):
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        })

    return _send


def asgi_auth_required(inner_app, *, required_tier: str = _MCP_REQUIRED_TIER):
    """Wrap a Starlette/ASGI app to require Bearer auth + tier check.

    Used to gate /mcp. Skips checks when CEREBRUM_MCP_DISABLE_AUTH=1 so
    local stdio/SSE testing doesn't have to mint a key.
    """
    if _MCP_DISABLE_AUTH:
        logger.warning(
            "security: CEREBRUM_MCP_DISABLE_AUTH=1 — /mcp is unauthenticated. "
            "Do not enable in production."
        )
        return inner_app

    # Lazy import to avoid circular dep at module-load (security imports
    # before main.py finishes module init).
    from app.core.auth import auth as auth_manager

    async def _wrapped(scope, receive, send):
        if scope.get("type") not in ("http",):
            # Non-HTTP (websocket, lifespan, etc.) — pass through. SSE is
            # plain HTTP so it's covered by the "http" branch.
            await inner_app(scope, receive, send)
            return

        headers = {
            k.decode().lower(): v.decode()
            for k, v in scope.get("headers", [])
        }
        auth_header = headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            await _send_status_only(401, "Authorization: Bearer <key> required")(send)
            return
        key = auth_header[7:].strip()

        # Reach into the auth manager directly — validate_key wants
        # HTTPAuthorizationCredentials and raises HTTPException, neither
        # of which fits ASGI cleanly.
        auth_manager._maybe_reload()
        key_data = auth_manager._keys.get(key)
        if not key_data:
            await _send_status_only(401, "Invalid API key")(send)
            return

        tier = key_data.get("tier")
        if required_tier and tier != required_tier:
            await _send_status_only(
                403,
                f"/mcp requires tier '{required_tier}'. Your tier: {tier}.",
            )(send)
            return

        await inner_app(scope, receive, send)

    return _wrapped


def enforce_tier_block_access(block_name: str, auth: Dict[str, Any]) -> None:
    """Server-side tier boundary: a free key reaches only its allowed blocks.

    Reads ``TIER_LIMITS[tier]["blocks_allowed"]`` — the declared (previously
    unenforced) per-tier block list. ``"all"`` means unrestricted.

    Tier strings are resolved through ``api_keys.TIER_ALIASES``. The audit
    found this function constructed ``Tier(str(raw_tier).lower())`` directly,
    which raises ValueError for "standard" and "unlimited" — the only two
    values the live authenticator issues — so the ``except ValueError:
    return`` branch swallowed every real request and the allowlist never
    applied. An unrecognised tier now fails CLOSED (most restrictive tier)
    and logs, rather than waving the request through.

    A caller with no ``tier`` key at all is left permissive: that shape only
    arises on internal call paths, and the primary gate
    ``enforce_block_access`` — which runs first and keys off "unlimited"
    directly — already covers the dangerous block set for it.
    """
    from app.core.api_keys import TIER_LIMITS, Tier, resolve_tier

    if not auth or "tier" not in auth:
        return
    raw_tier = auth.get("tier")
    if raw_tier is None:
        return
    tier = resolve_tier(raw_tier)
    if tier is None:
        logger.warning(
            "security: unrecognised tier %r — falling back to the most "
            "restrictive tier (%s). Add it to api_keys.TIER_ALIASES.",
            raw_tier, Tier.FREE.value,
        )
        tier = Tier.FREE
    allowed = TIER_LIMITS.get(tier, {}).get("blocks_allowed", "all")
    if allowed == "all" or block_name in allowed:
        return
    logger.warning(
        "security: blocked tier=%s from invoking block '%s' (not in tier allowance)",
        tier.value, block_name,
    )
    raise HTTPException(
        status_code=403,
        detail={
            "error": "tier_block_access_denied",
            "block": block_name,
            "tier": tier.value,
            "message": (
                f"Block '{block_name}' is not included in the {tier.value} tier. "
                "Upgrade to access it."
            ),
        },
    )
