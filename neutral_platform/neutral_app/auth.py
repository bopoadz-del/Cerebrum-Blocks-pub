"""Demo auth for the neutral proof platform.

This is an EXPLICIT STUB: /login maps a demo user directory to an
HMAC-signed principal token (sub, role, tenant_id, exp). A production
deployment replaces this with real SSO — the rest of the platform only
ever sees the authenticated principal, never client-supplied identity
fields (the kernel's own tenant-isolation rule).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional

# Required, no default: an unset secret refuses to sign or verify.
AUTH_SECRET = os.environ.get("NEUTRAL_AUTH_SECRET", "")
TOKEN_TTL_SECONDS = int(os.environ.get("NEUTRAL_TOKEN_TTL", "3600"))

# Demo directory: user -> role + tenant.
DEMO_DIRECTORY = {
    "u_alice": {"role": "requester", "tenant_id": "t1"},
    "u_bob": {"role": "supervisor", "tenant_id": "t1"},
    "u_carol": {"role": "maintenance_manager", "tenant_id": "t1"},
    "u_dave": {"role": "technician", "tenant_id": "t1"},
    "u_eve": {"role": "requester", "tenant_id": "t2"},
}


class AuthError(Exception):
    pass


def _sign(payload_b64: str) -> str:
    if not AUTH_SECRET:
        raise AuthError("NEUTRAL_AUTH_SECRET is not set (no default)")
    digest = hmac.new(AUTH_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def issue_token(user_id: str) -> str:
    entry = DEMO_DIRECTORY.get(user_id)
    if entry is None:
        raise AuthError(f"unknown demo user {user_id!r}")
    payload = {
        "sub": user_id,
        "role": entry["role"],
        "tenant_id": entry["tenant_id"],
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True).encode()
    ).rstrip(b"=").decode()
    return f"{payload_b64}.{_sign(payload_b64)}"


def verify_token(token: str) -> Dict[str, Any]:
    try:
        payload_b64, sig = token.split(".", 1)
    except ValueError:
        raise AuthError("malformed token") from None
    expected = _sign(payload_b64)
    if not hmac.compare_digest(expected, sig):
        raise AuthError("bad signature")
    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
    except (ValueError, UnicodeDecodeError):
        raise AuthError("bad payload") from None
    if int(payload.get("exp", 0)) < time.time():
        raise AuthError("token expired")
    if not payload.get("sub") or not payload.get("role") or not payload.get("tenant_id"):
        raise AuthError("principal missing fields")
    return payload


def principal_from_header(authorization: Optional[str]) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("missing bearer token")
    return verify_token(authorization[len("Bearer ") :])
