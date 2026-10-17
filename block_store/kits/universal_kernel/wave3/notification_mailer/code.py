"""Neutral notification dispatch primitives."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class NotificationChannel(str, Enum):
    """Supported notification channels."""

    email = "email"
    webhook = "webhook"
    slack = "slack"
    sms = "sms"


class NotificationError(Exception):
    """Raised when a notification cannot be sent."""


class MissingTransportError(NotificationError):
    """Raised when transport is configured but the delivery object is missing."""


@dataclass
class Message:
    """A neutral outbound message."""

    recipient: str
    channel: NotificationChannel
    subject: str = ""
    body: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.channel, str):
            self.channel = NotificationChannel(self.channel)


class NotificationMailer:
    """Neutral mailer with SMTP and webhook stubs; no real network calls unless configured."""

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        webhook_url: Optional[str] = None,
        transport: Optional[Any] = None,
    ) -> None:
        self.smtp_host = smtp_host or os.getenv("SMTP_HOST")
        self.smtp_port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = smtp_user or os.getenv("SMTP_USER")
        self.smtp_password = smtp_password or os.getenv("SMTP_PASSWORD")
        self.webhook_url = webhook_url or os.getenv("WEBHOOK_URL")
        self._transport = transport

    def send(self, message: Message) -> Dict[str, Any]:
        """Dispatch a message over its configured channel.

        When no real transport is configured, returns a fail-closed fallback
        dict labelled with ``honesty="no_transport_fallback"``.
        """
        if message.channel == NotificationChannel.email:
            return self._send_email(message)
        if message.channel == NotificationChannel.webhook:
            return self._send_webhook(message)
        if message.channel == NotificationChannel.slack:
            return self._send_webhook(message, slack_mode=True)
        if message.channel == NotificationChannel.sms:
            return self._send_sms(message)
        raise NotificationError(f"unsupported channel: {message.channel}")

    def _fallback(self, channel: str) -> Dict[str, Any]:
        return {
            "sent": False,
            "honesty": "no_transport_fallback",
            "queued": True,
            "channel": channel,
        }

    def _send_email(self, message: Message) -> Dict[str, Any]:
        if not self.smtp_host:
            return self._fallback("email")
        if self._transport is None:
            raise MissingTransportError("SMTP transport not configured")
        return self._transport.deliver(message)

    def _send_webhook(self, message: Message, slack_mode: bool = False) -> Dict[str, Any]:
        if not self.webhook_url:
            channel = "slack" if slack_mode else "webhook"
            return self._fallback(channel)
        if self._transport is None:
            raise MissingTransportError("webhook transport not configured")
        return self._transport.deliver(message)

    def _send_sms(self, message: Message) -> Dict[str, Any]:
        # The base kit does not ship an SMS transport; fail-closed fallback.
        return self._fallback("sms")
