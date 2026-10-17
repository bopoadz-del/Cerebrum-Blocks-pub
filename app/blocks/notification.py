"""Notification Hub Block — One endpoint for Email, Webhook, SMTP, Slack, MCP.

Delivery channels with a real outbound path and a delivery record:

``webhook``  POST JSON to ``NOTIFY_WEBHOOK_URL`` (operator env) or to a
             caller-supplied ``url``. The body is serialized ONCE to bytes,
             the HMAC-SHA256 (``NOTIFY_WEBHOOK_SECRET``) is computed over
             THOSE bytes, and THOSE bytes are what is sent -- a receiver can
             verify ``X-Cerebrum-Signature`` by recomputing over the body it
             received. ``X-Cerebrum-Timestamp`` is wall-clock UTC seconds.
             Two retries on 5xx / transport errors, none on 4xx.
``smtp``     stdlib ``smtplib`` behind ``SMTP_URL``
             (``smtp://[user:pass@]host[:port]``, ``smtps://`` for implicit
             TLS, ``smtp+starttls://`` to require STARTTLS). Same envelope
             as the webhook, same delivery record. Credentials are never
             sent on a connection that did not negotiate TLS.

When the env var for a channel is unset the notification goes to the
in-process OUTBOX and the result says so (``status: "outbox"``,
``sent: false``, ``delivery.mode: "outbox"``). Nothing is claimed delivered
that did not leave the process.
"""

import hashlib
import hmac
import json
import logging
import os
import smtplib
import ssl
import time
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from app.core.url_guard import UnsafeURLError, validate_outbound_url

logger = logging.getLogger(__name__)
from pydantic import BaseModel, Field

from app.core.universal_base import UniversalBlock
from app.core.typed_block import TypedBlock, Schema, ContentType


class NotificationEvent(BaseModel):
    """Event emitted by the notification hub."""
    event_type: str = Field(..., description="Event type: cost_threshold, swarm_complete, capture_done, etc.")
    source_block: str = Field(default="unknown")
    payload: Dict = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class NotificationHub:
    """Event bus for pub/sub notifications across all blocks."""

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable):
        """Subscribe to an event type. Callback receives NotificationEvent."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable):
        """Unsubscribe from an event type."""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [cb for cb in self._subscribers[event_type] if cb != callback]

    async def emit(self, event: NotificationEvent):
        """Publish event to all subscribers."""
        subscribers = self._subscribers.get(event.event_type, [])
        for callback in subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as exc:
                # Non-blocking: one subscriber must not break the others, but
                # the failure is named, not swallowed.
                logger.warning("notification subscriber for %s failed: %s", event.event_type, exc)

    async def send_and_emit(self, channel: str, message: str, result: Dict, source: str = "notification"):
        """Emit a delivery event after sending."""
        await self.emit(NotificationEvent(
            event_type=f"notification.{channel}",
            source_block=source,
            payload={"message": message, "result": result},
            timestamp=time.time()
        ))

    def get_subscriber_counts(self) -> Dict[str, int]:
        """Get count of subscribers per event type."""
        return {et: len(subs) for et, subs in self._subscribers.items()}


import asyncio
from app.core.http_errors import UNAVAILABLE

# Global instance for cross-block pub/sub
notification_hub = NotificationHub()


class NotificationBlock(TypedBlock):
    """Unified notification dispatcher."""

    name = "notification"
    version = "1.1.0"
    description = "Send notifications via Email, signed Webhook, SMTP, Slack, or MCP; undeliverable ones land in a declared outbox"
    layer = 2
    tags = ["notification", "messaging", "integration", "core"]
    requires = []

    input_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=["channel", "message"],
        optional_fields=["to", "subject", "html", "url", "headers", "payload", "blocks", "event", "source"],
        format_hints={}
    )

    output_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=["status", "channel"],
        optional_fields=["sent", "message_id", "http_status", "response_preview", "delivery", "note", "error"],
        format_hints={}
    )

    accepted_input_types = ["JSON", "NotificationRequest"]
    produced_output_types = ["JSON", "NotificationResult"]


    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        # Offline outbox: envelopes that had no configured live channel.
        self._outbox: List[Dict[str, Any]] = []

    async def execute(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        action = params.get("action") if isinstance(params, dict) else None
        if isinstance(input_data, str):
            input_data = {"message": input_data}
        return await super().execute(input_data, params)

    def validate_input(self, data: Any) -> Dict[str, Any]:
        if isinstance(data, dict) and data.get("action") in {"health", "status", "list", "history", "get", "unschedule", "broadcast", "search", "summarize", "structure", "execute_async", "outbox"}:
            return {"valid": True, "errors": [], "warnings": [], "data": data}
        return super().validate_input(data)

    default_config = {
        "sendgrid_api_key": os.getenv("SENDGRID_API_KEY", ""),
        "smtp_host": os.getenv("SMTP_HOST", ""),
        "smtp_port": int(os.getenv("SMTP_PORT", "587")),
        "smtp_user": os.getenv("SMTP_USER", ""),
        "smtp_pass": os.getenv("SMTP_PASS", ""),
        "slack_webhook_url": os.getenv("SLACK_WEBHOOK_URL", ""),
        "default_from_email": os.getenv("DEFAULT_FROM_EMAIL", "cerebrum@localhost"),
    }

    ui_schema = {
        "input": {
            "type": "json",
            "accept": None,
            "placeholder": '{"channel": "email", "to": "ops@example.com", "message": "Hello"}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "channel", "type": "text", "label": "Channel"},
                {"name": "sent", "type": "boolean", "label": "Sent"},
                {"name": "message_id", "type": "text", "label": "Message ID"},
            ],
        },
        "params": [
            {
                "name": "action",
                "type": "select",
                "label": "Action",
                "options": ["send", "broadcast", "health", "outbox"],
                "default": "send",
            },
        ],
        "quick_actions": [
            {"icon": "✉️", "label": "Send Email", "prompt": "Send an email notification"},
            {"icon": "🔗", "label": "Webhook", "prompt": "POST signed JSON to NOTIFY_WEBHOOK_URL"},
            {"icon": "📮", "label": "SMTP", "prompt": "Send via SMTP_URL"},
        ],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        action = params.get("action") or data.get("action", "send")

        if action == "send":
            return await self._send(data)
        elif action == "broadcast":
            return await self._broadcast(data)
        elif action == "health":
            return self._health_check()
        elif action == "outbox":
            return self._list_outbox(data)
        else:
            return {"status": "error", "error": f"Unknown action: {action}"}

    # ── Core Send ──────────────────────────────────────────────────────────────

    async def _send(self, data: Dict) -> Dict:
        channel = (data.get("channel") or "").lower()
        if not channel:
            return {
                "status": "error",
                "error": "channel required: one of mcp | email | webhook | smtp | slack",
            }
        handlers = {
            "mcp": self._send_mcp,
            "email": self._send_email,
            "webhook": self._send_webhook,
            "smtp": self._send_smtp_url,
            "slack": self._send_slack,
        }
        handler = handlers.get(channel)
        if not handler:
            return {"status": "error", "error": f"Unknown channel: {channel}"}
        result = await handler(data)

        # Emit event for subscribers (non-blocking)
        if result.get("status") == "success":
            try:
                await notification_hub.send_and_emit(
                    channel=channel,
                    message=data.get("message", ""),
                    result=result,
                    source=self.name,
                )
            except Exception as exc:
                logger.warning("notification hub emit failed after %s delivery: %s", channel, exc)

        return result

    async def _broadcast(self, data: Dict) -> Dict:
        """Send to multiple channels at once."""
        channels = data.get("channels") or []
        if not channels:
            return {
                "status": "error",
                "error": "channels required: any of mcp | email | webhook | smtp | slack",
            }
        results = []
        for channel in channels:
            result = await self._send({**data, "channel": channel})
            results.append({"channel": channel, **result})
        sent_all = all(r.get("status") == "success" for r in results)
        return {
            "status": "success" if sent_all else "partial",
            "results": results,
        }

    # ── MCP (Model Context Protocol) ───────────────────────────────────────────

    async def _send_mcp(self, data: Dict) -> Dict:
        """Send notification via MCP — calls a block as an MCP tool."""
        import json
        block_name = data.get("block") or data.get("tool")
        payload = data.get("payload") or data.get("message") or data.get("input", {})
        params = data.get("params", {})

        if not block_name:
            return {"status": "error", "error": "block or tool name required for MCP channel"}

        try:
            from app.blocks import BLOCK_REGISTRY

            try:
                from app.dependencies import _create_block_instance
            except ImportError:
                # Standalone/vendored runtime (a factory-built platform):
                # there is no platform wiring, tier gate or memory cache to
                # thread through, and plain construction is exactly what the
                # block adapters themselves do. Inside the Blocks platform
                # the import succeeds and nothing changes.
                def _create_block_instance(block_class, config=None, allow_platform=True):
                    return block_class()

            if block_name not in BLOCK_REGISTRY:
                return {"status": "error", "error": f"Block '{block_name}' not found"}

            block = _create_block_instance(BLOCK_REGISTRY[block_name])
            result = await block.execute(payload, params)
            return {
                "status": "success",
                "channel": "mcp",
                "sent": True,
                "block": block_name,
                "result_preview": json.dumps(result, default=str)[:500],
            }
        except Exception as e:
            return {"status": "error", "error": f"MCP dispatch failed: {e}"}

    # ── Email ──────────────────────────────────────────────────────────────────

    async def _send_email(self, data: Dict) -> Dict:
        import httpx
        to = data.get("to") or data.get("email")
        subject = data.get("subject", "Cerebrum Notification")
        body = data.get("message") or data.get("body", "")
        html = data.get("html", "")

        if not to:
            return {"status": "error", "error": "to (email) required"}

        # Try SendGrid first
        sg_key = self.config.get("sendgrid_api_key")
        if sg_key:
            return await self._send_sendgrid(to, subject, body, html, sg_key)

        # Fallback SMTP
        return await self._send_smtp(to, subject, body, html)

    async def _send_sendgrid(self, to: str, subject: str, body: str, html: str, api_key: str) -> Dict:
        import httpx
        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": self.config.get("default_from_email")},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": body},
            ],
        }
        if html:
            payload["content"].append({"type": "text/html", "value": html})

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                if resp.status_code in (200, 202):
                    return {"status": "success", "channel": "email", "sent": True}
                return {"status": "error", "error": f"SendGrid error: {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "error": f"SendGrid failed: {e}"}

    async def _send_smtp(self, to: str, subject: str, body: str, html: str) -> Dict:
        host = self.config.get("smtp_host")
        port = self.config.get("smtp_port", 587)
        user = self.config.get("smtp_user")
        password = self.config.get("smtp_pass")
        from_email = self.config.get("default_from_email")

        if not host:
            return {"status": "error", "error": "SMTP not configured (set SMTP_HOST or SENDGRID_API_KEY)", "error_kind": UNAVAILABLE}

        try:
            import aiosmtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_email
            msg["To"] = to
            msg.attach(MIMEText(body, "plain"))
            if html:
                msg.attach(MIMEText(html, "html"))

            await aiosmtplib.send(
                msg,
                hostname=host,
                port=port,
                username=user,
                password=password,
                start_tls=True if port == 587 else False,
            )
            return {"status": "success", "channel": "email", "sent": True}
        except ImportError:
            return {"status": "error", "error": "aiosmtplib not installed. Run: pip install aiosmtplib"}
        except Exception as e:
            return {"status": "error", "error": f"SMTP failed: {e}"}

    # ── Envelope, delivery record, outbox ─────────────────────────────────────

    WEBHOOK_RETRIES = 2   # retries after the first attempt (3 attempts total)
    OUTBOX_LIMIT = 1000

    @staticmethod
    def _env(name: str) -> str:
        return os.getenv(name, "").strip()

    @staticmethod
    def _truthy(value: str) -> bool:
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _envelope(self, data: Dict, channel: str) -> Dict[str, Any]:
        """The one envelope every live channel carries and every record names."""
        payload = data.get("payload")
        return {
            "id": uuid.uuid4().hex,
            "channel": channel,
            "event": str(data.get("event") or "notification"),
            "source": str(data.get("source") or self.name),
            "subject": str(data.get("subject") or ""),
            "message": str(data.get("message") or data.get("body") or ""),
            "payload": payload if isinstance(payload, dict) else ({} if payload is None else {"value": payload}),
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _redact_target(url: str) -> str:
        """scheme://host[:port]/path -- never userinfo, never the query."""
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{host}{port}{parsed.path or ''}"

    def _to_outbox(self, channel: str, data: Dict, reason: str) -> Dict:
        envelope = self._envelope(data, channel)
        self._outbox.append({"envelope": envelope, "reason": reason})
        if len(self._outbox) > self.OUTBOX_LIMIT:
            del self._outbox[: len(self._outbox) - self.OUTBOX_LIMIT]
        record = {
            "id": envelope["id"],
            "channel": channel,
            "mode": "outbox",
            "delivered": False,
            "attempts": 0,
            "target": None,
            "reason": reason,
            "outbox_size": len(self._outbox),
        }
        return {
            "status": "outbox",
            "channel": channel,
            "sent": False,
            "message_id": envelope["id"],
            "delivery": record,
            "note": f"nothing left the process: {reason}",
        }

    def _list_outbox(self, data: Dict) -> Dict:
        limit = int(data.get("limit") or 50)
        entries = self._outbox[-limit:]
        return {
            "status": "success",
            "channel": "outbox",
            "count": len(self._outbox),
            "entries": [
                {"id": e["envelope"]["id"], "channel": e["envelope"]["channel"],
                 "event": e["envelope"]["event"], "reason": e["reason"],
                 "recorded_at": e["envelope"]["sent_at"]}
                for e in entries
            ],
        }

    # ── Webhook ────────────────────────────────────────────────────────────────

    async def _send_webhook(self, data: Dict) -> Dict:
        import asyncio
        import httpx

        # Caller-supplied URL: `url`, `webhook_url`, or an http(s) URL in the
        # unified `to` field. Guarded as a CALLER URL: public hosts only.
        url = data.get("url") or data.get("webhook_url")
        if not url:
            candidate = data.get("to")
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                url = candidate
        if url:
            url_source, allow_private = "caller", False
        else:
            # Operator-configured URL. The operator may declare, in env, that
            # their sink is on loopback / a private network. Link-local
            # (cloud metadata) stays refused in every mode (app.core.url_guard).
            url = self._env("NOTIFY_WEBHOOK_URL")
            url_source = "env:NOTIFY_WEBHOOK_URL"
            allow_private = self._truthy(self._env("NOTIFY_WEBHOOK_ALLOW_PRIVATE"))
        if not url:
            return self._to_outbox("webhook", data, "NOTIFY_WEBHOOK_URL not set and no url supplied")

        try:
            url = await asyncio.to_thread(validate_outbound_url, url, allow_private)
        except UnsafeURLError as e:
            return {"status": "error", "channel": "webhook", "sent": False,
                    "error": f"unsafe webhook url ({url_source}): {e}"}

        method = str(data.get("method") or "POST").upper()
        if method != "POST":
            return {"status": "error", "channel": "webhook", "sent": False,
                    "error": f"webhook channel delivers a signed POST only (got {method})"}

        envelope = self._envelope(data, "webhook")
        # Serialize ONCE. Sign these bytes. Send these bytes.
        body = json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")

        headers: Dict[str, str] = {}
        extra = data.get("headers")
        if isinstance(extra, dict):
            headers.update({str(k): str(v) for k, v in extra.items()})
        headers.update({
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": f"cerebrum-notification/{self.version}",
            "X-Cerebrum-Delivery-Id": envelope["id"],
            "X-Cerebrum-Event": envelope["event"],
            # Wall-clock UTC seconds (not a monotonic loop reading).
            "X-Cerebrum-Timestamp": str(int(time.time())),
        })
        secret = self._env("NOTIFY_WEBHOOK_SECRET")
        signed = bool(secret)
        if signed:
            digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            headers["X-Cerebrum-Signature"] = f"sha256={digest}"

        target = self._redact_target(url)
        timeout = float(self.config.get("webhook_timeout") or 10)
        configured_backoff = self.config.get("webhook_retry_backoff")
        backoff = 0.5 if configured_backoff is None else float(configured_backoff)
        attempts = 0
        last_error: Optional[str] = None
        http_status: Optional[int] = None
        preview = ""
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            for attempt in range(1, self.WEBHOOK_RETRIES + 2):
                attempts = attempt
                try:
                    resp = await client.post(url, content=body, headers=headers)
                except httpx.HTTPError as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                else:
                    http_status = resp.status_code
                    preview = resp.text[:500]
                    if resp.status_code < 400:
                        record = {
                            "id": envelope["id"], "channel": "webhook", "mode": "live",
                            "delivered": True, "attempts": attempts, "target": target,
                            "url_source": url_source, "signed": signed,
                            "http_status": http_status, "sent_at": envelope["sent_at"],
                            "bytes": len(body),
                        }
                        return {
                            "status": "success", "channel": "webhook", "sent": True,
                            "message_id": envelope["id"], "http_status": http_status,
                            "response_preview": preview, "delivery": record,
                        }
                    last_error = f"HTTP {resp.status_code}"
                    if resp.status_code < 500:
                        break  # a client error will not change on retry
                if attempt <= self.WEBHOOK_RETRIES and backoff > 0:
                    await asyncio.sleep(backoff * attempt)

        record = {
            "id": envelope["id"], "channel": "webhook", "mode": "live",
            "delivered": False, "attempts": attempts, "target": target,
            "url_source": url_source, "signed": signed,
            "http_status": http_status, "sent_at": envelope["sent_at"],
            "error": last_error, "bytes": len(body),
        }
        return {
            "status": "error", "channel": "webhook", "sent": False,
            "message_id": envelope["id"], "http_status": http_status,
            "response_preview": preview, "delivery": record,
            "error": f"webhook delivery failed after {attempts} attempt(s): {last_error}",
        }

    # ── SMTP (stdlib smtplib, SMTP_URL) ────────────────────────────────────────

    @staticmethod
    def _smtp_deliver(host: str, port: int, scheme: str, user: Optional[str], password: Optional[str],
                      from_addr: str, to_addrs: List[str], msg: EmailMessage, timeout: float) -> Dict[str, Any]:
        """Blocking send; runs in a worker thread. Raises smtplib.SMTPException / OSError."""
        context = ssl.create_default_context()
        if scheme == "smtps":
            client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
            tls = True
        else:
            client = smtplib.SMTP(host, port, timeout=timeout)
            tls = False
        with client:
            client.ehlo()
            if not tls:
                if client.has_extn("starttls"):
                    client.starttls(context=context)
                    client.ehlo()
                    tls = True
                elif scheme == "smtp+starttls":
                    raise smtplib.SMTPException("server does not offer STARTTLS (required by smtp+starttls://)")
            if user:
                if not tls:
                    raise smtplib.SMTPException(
                        "refusing to send SMTP credentials without TLS; use smtps:// or a server that offers STARTTLS"
                    )
                client.login(user, password or "")
            refused = client.send_message(msg, from_addr=from_addr, to_addrs=to_addrs)
            return {"tls": tls, "refused": {k: v[0] for k, v in refused.items()}}

    async def _send_smtp_url(self, data: Dict) -> Dict:
        import asyncio

        smtp_url = self._env("SMTP_URL")
        if not smtp_url:
            return self._to_outbox("smtp", data, "SMTP_URL not set")

        parsed = urlparse(smtp_url)
        scheme = parsed.scheme.lower()
        if scheme not in ("smtp", "smtps", "smtp+starttls") or not parsed.hostname:
            return {"status": "error", "channel": "smtp", "sent": False,
                    "error": "SMTP_URL must be smtp://, smtps:// or smtp+starttls:// with a host"}
        host = parsed.hostname
        port = parsed.port or (465 if scheme == "smtps" else 587)
        user = unquote(parsed.username) if parsed.username else None
        password = unquote(parsed.password) if parsed.password else None
        query = parse_qs(parsed.query)
        from_addr = (
            (query.get("from") or [None])[0]
            or self._env("NOTIFY_SMTP_FROM")
            or self.config.get("default_from_email")
            or "cerebrum@localhost"
        )
        to = data.get("to") or data.get("email") or self._env("NOTIFY_SMTP_TO")
        if not to:
            return {"status": "error", "channel": "smtp", "sent": False,
                    "error": "to (email) required, or set NOTIFY_SMTP_TO"}
        raw_addrs = to if isinstance(to, list) else str(to).split(",")
        to_addrs = [t.strip() for t in raw_addrs if t and t.strip()]

        envelope = self._envelope(data, "smtp")
        msg = EmailMessage()
        msg["Subject"] = envelope["subject"] or f"[{envelope['source']}] {envelope['event']}"
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addrs)
        msg["Date"] = format_datetime(datetime.now(timezone.utc))
        msg["X-Cerebrum-Delivery-Id"] = envelope["id"]
        msg["X-Cerebrum-Event"] = envelope["event"]
        msg.set_content(
            envelope["message"]
            + "\n\n-- envelope --\n"
            + json.dumps(envelope, indent=2, sort_keys=True, default=str)
        )
        html = data.get("html")
        if html:
            msg.add_alternative(str(html), subtype="html")

        target = f"{scheme}://{host}:{port}"
        timeout = float(self.config.get("smtp_timeout") or 15)
        configured_backoff = self.config.get("smtp_retry_backoff")
        backoff = 0.5 if configured_backoff is None else float(configured_backoff)
        attempts = 0
        last_error: Optional[str] = None
        for attempt in range(1, self.WEBHOOK_RETRIES + 2):
            attempts = attempt
            try:
                outcome = await asyncio.to_thread(
                    self._smtp_deliver, host, port, scheme, user, password, from_addr, to_addrs, msg, timeout
                )
            except (smtplib.SMTPException, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                policy_refusal = (
                    isinstance(exc, (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused))
                    or "refusing to send SMTP credentials" in str(exc)
                    or "does not offer STARTTLS" in str(exc)
                )
                if policy_refusal:
                    break  # retrying will not change a policy or auth refusal
            else:
                record = {
                    "id": envelope["id"], "channel": "smtp", "mode": "live",
                    "delivered": True, "attempts": attempts, "target": target,
                    "tls": outcome["tls"], "authenticated": bool(user),
                    "recipients": to_addrs, "refused": outcome["refused"],
                    "sent_at": envelope["sent_at"],
                }
                return {"status": "success", "channel": "smtp", "sent": True,
                        "message_id": envelope["id"], "delivery": record}
            if attempt <= self.WEBHOOK_RETRIES and backoff > 0:
                await asyncio.sleep(backoff * attempt)

        record = {
            "id": envelope["id"], "channel": "smtp", "mode": "live",
            "delivered": False, "attempts": attempts, "target": target,
            "authenticated": False, "recipients": to_addrs,
            "sent_at": envelope["sent_at"], "error": last_error,
        }
        return {"status": "error", "channel": "smtp", "sent": False,
                "message_id": envelope["id"], "delivery": record,
                "error": f"smtp delivery failed after {attempts} attempt(s): {last_error}"}

    # ── Slack ──────────────────────────────────────────────────────────────────

    async def _send_slack(self, data: Dict) -> Dict:
        import httpx
        url = data.get("webhook_url") or self.config.get("slack_webhook_url")
        text = data.get("message") or data.get("text", "")
        blocks = data.get("blocks")

        if not url:
            return {"status": "error", "error": "Slack webhook URL not configured", "error_kind": UNAVAILABLE}

        payload = {"text": text}
        if blocks:
            payload["blocks"] = blocks

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200 and resp.text == "ok":
                    return {"status": "success", "channel": "slack", "sent": True}
                return {"status": "error", "error": f"Slack error: {resp.status_code} {resp.text}"}
        except Exception as e:
            return {"status": "error", "error": f"Slack failed: {e}"}

    # ── Health ─────────────────────────────────────────────────────────────────

    def _health_check(self) -> Dict:
        channels = []
        channels.append("mcp")
        if self.config.get("sendgrid_api_key") or self.config.get("smtp_host"):
            channels.append("email")
        if self.config.get("slack_webhook_url"):
            channels.append("slack")
        channels.append("webhook")
        channels.append("smtp")
        webhook_live = bool(self._env("NOTIFY_WEBHOOK_URL"))
        smtp_live = bool(self._env("SMTP_URL"))
        return {
            "status": "healthy",
            "available_channels": channels,
            # Live means an env target is configured; otherwise the channel
            # records to the in-process outbox and says so per result.
            "delivery": {
                "webhook": "live" if webhook_live else "outbox",
                "webhook_signed": bool(self._env("NOTIFY_WEBHOOK_SECRET")),
                "smtp": "live" if smtp_live else "outbox",
                "outbox_size": len(self._outbox),
            },
            "block_id": self.name,
            "version": self.version,
        }
