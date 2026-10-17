"""Inbound webhook receiver — HMAC-SHA256 signature verification.

Ported from the Cerebrum donor's webhook security layer
(backend/app/core/security/webhook_security.py, WebhookSignature) with the
Django coupling removed: same header format ``t=<unix_ts>,v1=<hex_digest>``,
same signature base ``f"{timestamp}.{canonical_json(payload)}"``, same
5-minute replay window, same constant-time comparison.

The block verifies and names refusals — it never stores payloads or secrets
on its own. Per-source secrets live in the block config
(``config["sources"] = {"procore": "whsec_..."}``) so a caller that cannot
name its source is refused.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, Optional, Tuple

from app.core.universal_base import UniversalBlock

SIGNATURE_VERSION = "v1"
TIMESTAMP_TOLERANCE_SECONDS = 300


def _canonical_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _signature_base(timestamp: int, payload: Dict[str, Any]) -> str:
    return f"{timestamp}.{_canonical_json(payload)}"


def sign_payload(payload: Dict[str, Any], secret: str, timestamp: Optional[int] = None) -> str:
    """Build a signature header for ``payload`` under ``secret``."""
    if timestamp is None:
        timestamp = int(time.time())
    digest = hmac.new(
        secret.encode("utf-8"),
        _signature_base(timestamp, payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},{SIGNATURE_VERSION}={digest}"


def _parse_header(header: str) -> Tuple[int, str]:
    """Parse ``t=<ts>,v1=<sig>``. Raises ValueError on malformed input."""
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    timestamp = int(parts["t"])
    signature = parts[SIGNATURE_VERSION]
    return timestamp, signature


def verify_signature(
    payload: Dict[str, Any],
    signature_header: str,
    secret: str,
    *,
    now: Optional[int] = None,
) -> Tuple[bool, str]:
    """Verify an incoming signature. Returns (ok, reason).

    Reasons: "ok", "malformed_header", "stale_timestamp", "invalid_signature".
    """
    try:
        timestamp, presented = _parse_header(signature_header)
    except (KeyError, ValueError):
        return False, "malformed_header"
    current = int(time.time()) if now is None else int(now)
    if abs(current - timestamp) > TIMESTAMP_TOLERANCE_SECONDS:
        return False, "stale_timestamp"
    expected = sign_payload(payload, secret, timestamp=timestamp)
    _ts, expected_sig = _parse_header(expected)
    if not hmac.compare_digest(presented, expected_sig):
        return False, "invalid_signature"
    return True, "ok"


class InboundWebhookBlock(UniversalBlock):
    """Verify inbound webhook deliveries against per-source HMAC secrets.

    Fail-closed by construction: an unnamed source, a missing header, a
    stale timestamp, or a mismatched signature is refused with the reason
    named — never silently accepted.
    """

    name = "inbound_webhook"
    version = "1.0.0"
    requires: list = []
    layer = 1
    tags = ["integration", "webhook", "security", "connector-infra"]

    default_config: Dict[str, Any] = {
        # {"<source>": "whsec_..."} — set by the operator per integration.
        "sources": {},
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        action = params.get("action")
        if not action and isinstance(input_data, dict):
            action = input_data.get("action")
        action = action or "verify"
        if not isinstance(input_data, dict):
            return {"error": "input must be a dict"}

        if action == "sign":
            return self._sign(input_data)
        if action == "verify":
            return self._verify(input_data)
        if action == "generate_secret":
            return {"secret": "whsec_" + secrets.token_urlsafe(32)}
        return {"error": f"Unknown action: {action}", "available": ["verify", "sign", "generate_secret"]}

    def _source_secret(self, source: str) -> Optional[str]:
        sources = self.config.get("sources") or {}
        return sources.get(source)

    def _sign(self, data: Dict) -> Dict:
        source = str(data.get("source") or "")
        payload = data.get("payload")
        if not isinstance(payload, dict):
            return {"error": "payload must be a dict"}
        secret = self._source_secret(source)
        if not secret:
            return {"error": f"unknown source: {source!r}"}
        return {"signature": sign_payload(payload, secret)}

    def _verify(self, data: Dict) -> Dict:
        source = str(data.get("source") or "")
        payload = data.get("payload")
        header = data.get("signature") or data.get("signature_header")
        if not isinstance(payload, dict):
            return {"error": "payload must be a dict"}
        if not header:
            return {"verified": False, "error": "signature header missing"}
        secret = self._source_secret(source)
        if not secret:
            return {"verified": False, "error": f"unknown source: {source!r}"}
        ok, reason = verify_signature(payload, str(header), secret)
        if not ok:
            return {"verified": False, "error": reason}
        return {"verified": True, "source": source}
