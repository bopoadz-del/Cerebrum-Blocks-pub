"""Sentry must not ship customer secret material off the box.

Shape: build the event Sentry would actually construct for an exception
raised while handling a realistic POST /v1/execute with block="secrets",
run it through the real `before_send` hook, serialise the result, and
assert the sentinel secret is nowhere in the bytes.

This deliberately does not assert "before_send is configured" — that was
true of the configuration audit and told us nothing about whether the
secret survives. The sentinel is planted in every place the SDK actually
puts it: the request body, a stack-frame local, a request header, a
breadcrumb, and interpolated into the exception message itself.
"""

from __future__ import annotations

import json

import pytest

from app.core.logging_config import scrub_event


SENTINEL = "sk_live_TESTSENTINEL_9f3a2b7c1d0e4f5a6b8c9d0e"
SENTINEL_PASSWORD = __import__("secrets").token_urlsafe(27)


def _execute_secrets_event() -> dict:
    """The event sentry-sdk builds for a failure inside app/blocks/secrets.py."""
    return {
        "event_id": "abc123",
        "level": "error",
        "transaction": "POST /v1/execute",
        "environment": "production",
        "request": {
            "url": "https://api.example.com/v1/execute",
            "method": "POST",
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {SENTINEL}",
                "User-Agent": "curl/8.0",
            },
            "cookies": {"session": SENTINEL},
            "data": json.dumps(
                {
                    "block": "secrets",
                    "input": {
                        "action": "set",
                        "name": "stripe_live",
                        "value": SENTINEL,
                    },
                    "params": {"master_key": SENTINEL_PASSWORD},
                }
            ),
        },
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": f"could not encrypt secret {SENTINEL}",
                    "module": "app.blocks.secrets",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "app/blocks/secrets.py",
                                "function": "_set_secret",
                                "lineno": 143,
                                "vars": {
                                    "name": "stripe_live",
                                    "value": SENTINEL,
                                    "data": {"value": SENTINEL},
                                    "self": "<SecretsBlock>",
                                },
                            }
                        ]
                    },
                }
            ]
        },
        "breadcrumbs": {
            "values": [
                {
                    "category": "block",
                    "message": "executing secrets",
                    "data": {"api_key": SENTINEL, "block": "secrets"},
                }
            ]
        },
        "extra": {"payload": {"value": SENTINEL}},
        "contexts": {"runtime": {"name": "CPython", "version": "3.11.9"}},
    }


def _serialise(event) -> str:
    return json.dumps(event, default=str)


def test_secret_value_never_leaves_the_process():
    scrubbed = scrub_event(_execute_secrets_event(), None)
    assert scrubbed is not None, "the event must be scrubbed, not dropped wholesale"
    blob = _serialise(scrubbed)
    assert SENTINEL not in blob
    assert SENTINEL_PASSWORD not in blob


def test_scrubbed_event_is_still_diagnostically_useful():
    """A hook that returns None or {} would pass the leak test and destroy
    error reporting. Pin the fields an on-call engineer needs."""
    scrubbed = scrub_event(_execute_secrets_event(), None)
    assert scrubbed["transaction"] == "POST /v1/execute"
    assert scrubbed["level"] == "error"
    exc = scrubbed["exception"]["values"][0]
    assert exc["type"] == "ValueError"
    assert exc["module"] == "app.blocks.secrets"
    # The message is preserved apart from the redacted literal.
    assert "could not encrypt secret" in exc["value"]
    frame = exc["stacktrace"]["frames"][0]
    assert frame["filename"] == "app/blocks/secrets.py"
    assert frame["lineno"] == 143
    assert frame["vars"]["name"] == "stripe_live"
    assert scrubbed["request"]["method"] == "POST"
    assert scrubbed["contexts"]["runtime"]["name"] == "CPython"


@pytest.mark.parametrize("block", ["secrets", "config", "auth", "database", "billing"])
def test_sensitive_block_bodies_are_dropped_wholesale(block):
    """Field-level scrubbing loses to caller-chosen key names, so the whole
    input/params payload goes for these blocks."""
    event = {
        "request": {
            "url": "https://api.example.com/v1/execute",
            "method": "POST",
            "data": json.dumps(
                {
                    "block": block,
                    "input": {"innocuous_looking_field": SENTINEL},
                    "params": {"another_field": SENTINEL},
                }
            ),
        }
    }
    blob = _serialise(scrub_event(event, None))
    assert SENTINEL not in blob


def test_unparseable_execute_body_is_dropped():
    """If we cannot parse it we cannot reason about it, so it does not ship."""
    event = {
        "request": {
            "url": "https://api.example.com/v1/execute",
            "method": "POST",
            "data": "not json at all " + SENTINEL,
        }
    }
    blob = _serialise(scrub_event(event, None))
    assert SENTINEL not in blob


def test_non_sensitive_block_body_survives_scrubbing():
    """Guard against over-redaction: a chat payload is still debuggable."""
    event = {
        "request": {
            "url": "https://api.example.com/v1/execute",
            "method": "POST",
            "data": json.dumps(
                {"block": "chat", "input": {"text": "how do I price concrete"}}
            ),
        }
    }
    scrubbed = scrub_event(event, None)
    assert "how do I price concrete" in _serialise(scrubbed)


def test_transaction_event_spans_are_scrubbed():
    """`before_send_transaction` receives spans, not exceptions. Span data
    carries db.statement and request payloads."""
    event = {
        "type": "transaction",
        "transaction": "POST /v1/execute",
        "spans": [
            {
                "op": "db.query",
                "description": "SELECT 1",
                "data": {"db.statement": "SELECT 1", "connection_string": SENTINEL},
            },
            {"op": "http.client", "data": {"api_key": SENTINEL}},
        ],
    }
    scrubbed = scrub_event(event, None)
    blob = _serialise(scrubbed)
    assert SENTINEL not in blob
    # Still useful.
    assert scrubbed["spans"][0]["data"]["db.statement"] == "SELECT 1"
    assert scrubbed["spans"][0]["op"] == "db.query"
    assert scrubbed["transaction"] == "POST /v1/execute"


def test_scrub_hook_never_raises_on_malformed_input():
    for bad in (None, "string-event", 42, [], {"exception": "not-a-dict"}):
        scrub_event(bad, None)  # must not raise
