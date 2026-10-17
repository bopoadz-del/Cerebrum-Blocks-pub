"""Per-source HMAC webhook signature receivers (Procore/GitHub/Slack/Maximo).

Core verification ported from C:\\Users\\<owner>\\Cerebrum\\backend\\app\\core\\
security\\webhook_security.py: WebhookSignature (HMAC-SHA256, "t=<ts>,v1=<hex>"
header scheme, 5-minute replay window, constant-time compare) and
WebhookManager.verify_incoming_webhook.

Per-source schemes:
- github:  X-Hub-Signature-256 "sha256=<hex>" over the raw body (documented
  GitHub scheme).
- slack:   X-Slack-Signature "v0=<hex>" over "v0:<ts>:<raw body>" with
  X-Slack-Request-Timestamp, 5-minute tolerance (documented Slack scheme).
- procore: X-Procore-Signature, HMAC-SHA256 hex of the raw body (documented
  Procore scheme).
- maximo:  no published vendor scheme — uses the ported donor v1 scheme
  (t=<ts>,v1=<hex> over canonical JSON), the scheme this store signs with.
- cerebrum: alias of the ported donor v1 scheme.

Fail closed everywhere: a missing signature header, missing secret,
malformed header, stale timestamp, or mismatched signature is refused.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "hmac_webhook_receiver",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


SIGNATURE_VERSION = "v1"
TIMESTAMP_TOLERANCE_SECONDS = 300  # ported from webhook_security.py

SCHEMES = {
    "github": {
        "header": "X-Hub-Signature-256",
        "prefix": "sha256=",
        "body_basis": "raw",
    },
    "slack": {
        "header": "X-Slack-Signature",
        "prefix": "v0=",
        "body_basis": "v0:<ts>:<raw body>",
        "timestamp_header": "X-Slack-Request-Timestamp",
    },
    "procore": {
        "header": "X-Procore-Signature",
        "prefix": "",
        "body_basis": "raw",
    },
    "maximo": {
        "header": "X-Webhook-Signature",
        "prefix": "",
        "body_basis": "canonical-json",
    },
    "cerebrum": {
        "header": "X-Webhook-Signature",
        "prefix": "",
        "body_basis": "canonical-json",
    },
}


def generate_secret() -> str:
    """Ported from webhook_security.py WebhookSignature.generate_secret."""
    return "whsec_" + secrets.token_urlsafe(32)


def sign_payload(payload: Dict[str, Any], secret: str, timestamp: int = None) -> str:
    """Ported from webhook_security.py WebhookSignature.sign_payload."""
    if timestamp is None:
        timestamp = int(time.time())
    signed_payload = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    signature_base = f"{timestamp}.{signed_payload}"
    signature = hmac.new(
        secret.encode("utf-8"),
        signature_base.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},{SIGNATURE_VERSION}={signature}"


def _parse_signature_header(header: str):
    """Ported from webhook_security.py WebhookSignature._parse_signature_header."""
    parts = header.split(",")
    timestamp = None
    signature = None
    for part in parts:
        if part.startswith("t="):
            timestamp = int(part[2:])
        elif part.startswith(f"{SIGNATURE_VERSION}="):
            signature = part[len(SIGNATURE_VERSION) + 1:]
    if timestamp is None or signature is None:
        raise ValueError("Invalid signature header format")
    return timestamp, signature


class HmacWebhookReceiverBlock(UniversalBlock):
    """HMAC-SHA256 webhook signature verification — fail closed on any doubt."""

    name = "hmac_webhook_receiver"
    version = "1.0.0"
    description = (
        "real — per-source HMAC webhook receivers ported from "
        "C:\\Users\\<owner>\\Cerebrum\\backend\\app\\core\\security\\webhook_security.py "
        "(WebhookSignature sign/verify with 5-minute replay window and "
        "constant-time compare, WebhookManager.verify_incoming_webhook), plus the "
        "documented vendor header schemes for GitHub (X-Hub-Signature-256), Slack "
        "(X-Slack-Signature v0), Procore (X-Procore-Signature); Maximo uses the "
        "ported donor v1 scheme. Missing signature, missing secret, malformed "
        "header, stale timestamp, or mismatched signature is refused."
    )
    layer = 2
    tags = ["webhook", "security", "hmac", "signature", "procore", "github", "slack", "maximo"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"action": "verify", "source": "github", "body": "...", "headers": {"X-Hub-Signature-256": "sha256=..."}, "secret": "whsec_..."}',
            "multiline": True,
        },
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}]},
    }

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "verify")).lower()
        try:
            if action == "schemes":
                return _envelope("ok", {"sources": {
                    name: {"header": spec["header"], "body_basis": spec["body_basis"]}
                    for name, spec in SCHEMES.items()
                }})
            if action == "generate_secret":
                return _envelope("ok", {"secret": generate_secret()})
            if action == "sign":
                return self._sign(payload)
            if action == "verify":
                return self._verify(payload)
            return _envelope(
                "error",
                error=f"unknown action: {action}",
                detail={"known": ["verify", "sign", "generate_secret", "schemes"]},
            )
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    def _sign(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = payload.get("payload")
        secret = str(payload.get("secret", ""))
        if not secret:
            return _envelope("refused", error="secret is required to sign")
        if not isinstance(body, dict):
            return _envelope("error", error="sign requires a payload dict")
        timestamp = payload.get("timestamp")
        if timestamp is not None:
            try:
                timestamp = int(timestamp)
            except (TypeError, ValueError):
                return _envelope("error", error="timestamp must be an integer epoch")
        return _envelope("ok", {
            "signature_header": sign_payload(body, secret, timestamp),
            "scheme": "v1 (canonical JSON)",
        })

    def _verify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        source = str(payload.get("source", "")).lower()
        if source not in SCHEMES:
            return _envelope(
                "refused",
                error=f"unknown webhook source: {source}",
                detail={"known_sources": sorted(SCHEMES)},
            )
        secret = str(payload.get("secret", ""))
        if not secret:
            return _envelope(
                "refused",
                error="secret is required — refusing to verify without one",
                detail={"source": source},
            )
        spec = SCHEMES[source]
        headers = payload.get("headers") or {}
        if not isinstance(headers, dict):
            return _envelope("error", error="headers must be a dict")
        lookup = {str(k).lower(): str(v) for k, v in headers.items()}
        header_name = spec["header"].lower()
        signature = lookup.get(header_name, "")
        if not signature:
            return _envelope(
                "refused",
                error=f"missing signature header {spec['header']} — fail closed",
                detail={"source": source, "header": spec["header"]},
            )
        body = payload.get("body")
        if body is None:
            return _envelope(
                "refused",
                error="missing body — fail closed",
                detail={"source": source},
            )
        if source == "github":
            return self._verify_raw_hex(source, body, signature, secret, prefix="sha256=", header=spec["header"])
        if source == "procore":
            return self._verify_raw_hex(source, body, signature, secret, prefix="", header=spec["header"])
        if source == "slack":
            return self._verify_slack(source, body, signature, secret, lookup)
        # canonical-json (maximo / cerebrum): the ported donor v1 scheme.
        return self._verify_donor_scheme(source, body, signature, secret)

    def _verify_raw_hex(
        self,
        source: str,
        body: Any,
        signature: str,
        secret: str,
        prefix: str,
        header: str,
    ) -> Dict[str, Any]:
        raw = body if isinstance(body, str) else json.dumps(body)
        if prefix and not signature.startswith(prefix):
            return _envelope(
                "refused",
                error=f"malformed {header} (expected {prefix}<hex>)",
                detail={"source": source},
            )
        expected = hmac.new(secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
        provided = signature[len(prefix):] if prefix else signature
        if not hmac.compare_digest(provided, expected):
            return _envelope(
                "refused",
                error="signature mismatch — fail closed",
                detail={"source": source},
            )
        return _envelope("ok", {
            "verified": True,
            "source": source,
            "scheme": "raw-body hmac-sha256",
            "header": header,
        })

    def _verify_slack(self, source: str, body: Any, signature: str, secret: str, lookup: Dict[str, str]) -> Dict[str, Any]:
        if not signature.startswith("v0="):
            return _envelope(
                "refused",
                error="malformed X-Slack-Signature (expected v0=<hex>)",
                detail={"source": source},
            )
        ts_header = lookup.get("x-slack-request-timestamp", "")
        try:
            ts = int(ts_header)
        except (TypeError, ValueError):
            return _envelope(
                "refused",
                error="missing or non-integer X-Slack-Request-Timestamp",
                detail={"source": source},
            )
        if abs(int(time.time()) - ts) > TIMESTAMP_TOLERANCE_SECONDS:
            return _envelope(
                "refused",
                error="webhook timestamp outside tolerance window — replay refused",
                detail={"source": source, "tolerance_seconds": TIMESTAMP_TOLERANCE_SECONDS},
            )
        raw = body if isinstance(body, str) else json.dumps(body)
        expected = hmac.new(
            secret.encode("utf-8"),
            f"v0:{ts}:{raw}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature[len("v0="):], expected):
            return _envelope(
                "refused",
                error="signature mismatch — fail closed",
                detail={"source": source},
            )
        return _envelope("ok", {
            "verified": True,
            "source": source,
            "scheme": "slack v0",
            "header": "X-Slack-Signature",
        })

    def _verify_donor_scheme(self, source: str, body: Any, signature_header: str, secret: str) -> Dict[str, Any]:
        # Ported from webhook_security.py WebhookSignature.verify_signature
        # and WebhookManager.verify_incoming_webhook.
        try:
            payload = body if isinstance(body, dict) else json.loads(body)
        except (TypeError, ValueError):
            return _envelope(
                "refused",
                error="body is not valid JSON for the v1 canonical scheme — fail closed",
                detail={"source": source},
            )
        try:
            timestamp, signature = _parse_signature_header(signature_header)
        except (ValueError, TypeError):
            return _envelope(
                "refused",
                error="invalid signature header format (expected t=<ts>,v1=<hex>)",
                detail={"source": source},
            )
        current_time = int(time.time())
        if abs(current_time - timestamp) > TIMESTAMP_TOLERANCE_SECONDS:
            return _envelope(
                "refused",
                error="webhook timestamp outside tolerance window — replay refused",
                detail={"source": source, "tolerance_seconds": TIMESTAMP_TOLERANCE_SECONDS},
            )
        expected_header = sign_payload(payload, secret, timestamp)
        _, expected_sig = _parse_signature_header(expected_header)
        if not hmac.compare_digest(signature, expected_sig):
            return _envelope(
                "refused",
                error="signature mismatch — fail closed",
                detail={"source": source},
            )
        return _envelope("ok", {
            "verified": True,
            "source": source,
            "scheme": "v1 canonical-json",
            "header": "X-Webhook-Signature",
        })
