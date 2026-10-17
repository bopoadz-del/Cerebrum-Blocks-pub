"""Neutral notification mailer kit."""

from .code import (
    Message,
    MissingTransportError,
    NotificationChannel,
    NotificationError,
    NotificationMailer,
)

__all__ = [
    "Message",
    "MissingTransportError",
    "NotificationChannel",
    "NotificationError",
    "NotificationMailer",
]
