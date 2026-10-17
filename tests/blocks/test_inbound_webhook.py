"""inbound_webhook: HMAC-SHA256 verification, ported from the Cerebrum donor."""

from __future__ import annotations

import asyncio
import time

from app.blocks.inbound_webhook import (
    InboundWebhookBlock,
    sign_payload,
    verify_signature,
)


def _block(sources=None):
    b = InboundWebhookBlock()
    if sources:
        b.config = type(b.config)(b, {**b.default_config, "sources": sources})
    return b


def _run(block, action, **data):
    return asyncio.run(block.process(dict(data), params={"action": action}))


def test_round_trip_verifies():
    secret = "whsec_test"
    block = _block({"procore": secret})
    payload = {"event": "rfq.created", "id": 7}
    sig = _run(block, "sign", source="procore", payload=payload)["signature"]
    out = _run(block, "verify", source="procore", payload=payload, signature=sig)
    assert out["verified"] is True


def test_tampered_payload_is_refused():
    secret = "whsec_test"
    block = _block({"procore": secret})
    payload = {"event": "rfq.created", "id": 7}
    sig = _run(block, "sign", source="procore", payload=payload)["signature"]
    out = _run(
        block,
        "verify",
        source="procore",
        payload={"event": "rfq.created", "id": 8},
        signature=sig,
    )
    assert out["verified"] is False
    assert out["error"] == "invalid_signature"


def test_wrong_secret_is_refused():
    block = _block({"procore": "whsec_right"})
    payload = {"event": "rfq.created"}
    sig = sign_payload(payload, "whsec_wrong")
    out = _run(block, "verify", source="procore", payload=payload, signature=sig)
    assert out["verified"] is False
    assert out["error"] == "invalid_signature"


def test_stale_timestamp_is_refused():
    secret = "whsec_test"
    block = _block({"procore": secret})
    payload = {"event": "rfq.created"}
    sig = sign_payload(payload, secret, timestamp=int(time.time()) - 301)
    out = _run(block, "verify", source="procore", payload=payload, signature=sig)
    assert out["verified"] is False
    assert out["error"] == "stale_timestamp"


def test_missing_header_is_refused():
    block = _block({"procore": "whsec_test"})
    out = _run(block, "verify", source="procore", payload={"x": 1})
    assert out["verified"] is False
    assert "signature header missing" in out["error"]


def test_unknown_source_is_refused():
    block = _block({})
    payload = {"event": "rfq.created"}
    sig = sign_payload(payload, "whsec_x")
    out = _run(block, "verify", source="github", payload=payload, signature=sig)
    assert out["verified"] is False
    assert "unknown source" in out["error"]


def test_malformed_header_is_refused():
    block = _block({"procore": "whsec_test"})
    out = _run(block, "verify", source="procore", payload={"x": 1}, signature="garbage")
    assert out["verified"] is False
    assert out["error"] == "malformed_header"


def test_generate_secret_shape():
    block = _block()
    out = _run(block, "generate_secret")
    assert out["secret"].startswith("whsec_")
    assert len(out["secret"]) > 20
