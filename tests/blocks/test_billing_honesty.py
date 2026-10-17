"""Billing honesty: unimplemented paths must say so — never fake success."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.billing import BillingBlock


class _FakeStripe:
    class Webhook:
        @staticmethod
        def construct_event(payload, sig_header, secret):
            return {"type": payload.get("type", "unknown")}


def test_upgrade_plan_refuses_honestly():
    b = BillingBlock()
    r = asyncio.run(b._upgrade_plan({"api_key": "k", "plan": "pro"}))
    assert r["upgraded"] is False
    assert "not implemented" in r["error"]


def test_webhook_unimplemented_event_types_are_not_handled():
    b = BillingBlock()
    b.stripe = _FakeStripe()
    b.webhook_secret = "whsec_test"

    r1 = asyncio.run(
        b._handle_webhook(
            {"payload": {"type": "invoice.payment_succeeded"}, "signature": "sig"}
        )
    )
    assert r1["handled"] is False
    assert "not implemented" in r1["note"]

    r2 = asyncio.run(
        b._handle_webhook(
            {"payload": {"type": "customer.subscription.deleted"}, "signature": "sig"}
        )
    )
    assert r2["handled"] is False
    assert "not implemented" in r2["note"]

    r3 = asyncio.run(
        b._handle_webhook({"payload": {"type": "unknown.event"}, "signature": "sig"})
    )
    assert r3["handled"] is False
