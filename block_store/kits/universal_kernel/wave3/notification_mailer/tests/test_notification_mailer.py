"""Tests for the neutral notification mailer sub-kit."""

import pytest

from block_store.kits.universal_kernel.wave3.notification_mailer import (
    Message,
    MissingTransportError,
    NotificationChannel,
    NotificationMailer,
)


class FakeTransport:
    def __init__(self):
        self.messages = []

    def deliver(self, message):
        self.messages.append(message)
        return {"sent": True, "channel": message.channel.value}


def test_email_fallback_when_no_smtp_host():
    mailer = NotificationMailer()
    result = mailer.send(Message("a@example.com", NotificationChannel.email, "hi", "body"))
    assert result["sent"] is False
    assert result["honesty"] == "no_transport_fallback"
    assert result["queued"] is True


def test_webhook_fallback_when_no_url():
    mailer = NotificationMailer()
    result = mailer.send(Message("https://x", NotificationChannel.webhook, body="payload"))
    assert result["honesty"] == "no_transport_fallback"


def test_sms_fallback():
    mailer = NotificationMailer()
    result = mailer.send(Message("+123", NotificationChannel.sms, body="hi"))
    assert result["sent"] is False
    assert result["honesty"] == "no_transport_fallback"


def test_email_with_transport():
    transport = FakeTransport()
    mailer = NotificationMailer(smtp_host="smtp.example.com", transport=transport)
    result = mailer.send(Message("a@example.com", NotificationChannel.email, "hi", "body"))
    assert result["sent"] is True
    assert len(transport.messages) == 1


def test_webhook_with_transport():
    transport = FakeTransport()
    mailer = NotificationMailer(webhook_url="https://x", transport=transport)
    result = mailer.send(Message("https://x", NotificationChannel.webhook, body="payload"))
    assert result["sent"] is True
    assert result["channel"] == "webhook"


def test_email_config_missing_transport_raises():
    mailer = NotificationMailer(smtp_host="smtp.example.com")
    with pytest.raises(MissingTransportError):
        mailer.send(Message("a@example.com", NotificationChannel.email, "hi", "body"))


def test_message_channel_from_string():
    msg = Message("a@example.com", "email", "hi", "body")  # type: ignore[arg-type]
    assert msg.channel == NotificationChannel.email
