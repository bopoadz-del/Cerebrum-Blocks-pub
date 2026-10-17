"""Outbound webhook block: signatures, the SSRF guard, retries, and fan-out.

This is app/blocks/webhook.py (outgoing send/register/trigger). It is NOT
app/blocks/inbound_webhook.py, which tests/blocks/test_inbound_webhook.py
covers - a different block with a different contract.

Offline throughout. `aiohttp.ClientSession` is replaced with a recorder that
captures the URL, body and headers of every POST and replays scripted statuses;
`socket.getaddrinfo` is stubbed with a fixed host table so the real
app.core.url_guard logic runs against known addresses; `asyncio.sleep` is
captured so the exponential backoff is asserted rather than waited out.

Every assertion names a value WebhookBlock.process computed: the HMAC-SHA256 it
signed the body with, the refusal for a non-public URL, the retry schedule, and
which registered endpoints an event fanned out to.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import socket

import pytest

from app.blocks.webhook import WebhookBlock

_HOSTS = {
    "hooks.example.com": "93.184.216.34",
    "billing.example.com": "93.184.216.35",
    "audit.example.com": "93.184.216.36",
    "internal.example.com": "10.0.0.5",
}


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host in _HOSTS:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_HOSTS[host], port))]
        raise socket.gaierror(f"offline test: unknown host {host!r}")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


class _FakeResponse:
    def __init__(self, status, body=""):
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def text(self):
        return self._body


class _Recorder:
    """Replaces aiohttp.ClientSession; records posts, replays scripted statuses."""

    def __init__(self, script=((200, ""),)):
        self.script = list(script)
        self.posts = []
        self.sessions = 0

    def install(self, monkeypatch):
        import aiohttp

        recorder = self

        class _FakeSession:
            def __init__(self, *args, **kwargs):
                recorder.sessions += 1

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def post(self, url, *, json=None, headers=None, **kwargs):
                recorder.posts.append(
                    {"url": url, "json": json, "headers": headers, "kwargs": kwargs}
                )
                index = min(len(recorder.posts) - 1, len(recorder.script) - 1)
                status, body = recorder.script[index]
                return _FakeResponse(status, body)

        monkeypatch.setattr(aiohttp, "ClientSession", _FakeSession)
        return self


@pytest.fixture
def no_backoff(monkeypatch):
    """Capture the backoff schedule instead of sleeping through it."""
    delays = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds, *args, **kwargs):
        delays.append(seconds)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return delays


def _block(**config):
    base = {"secret": "s3cr3t", "max_retries": 3}
    base.update(config)
    return WebhookBlock(None, base)


def _expected_signature(secret: str, payload: dict) -> str:
    return hmac.new(secret.encode(), str(payload).encode(), hashlib.sha256).hexdigest()


# -- Dispatch ------------------------------------------------------------------


async def test_unknown_action_is_refused():
    out = await _block().process({}, {})

    assert out == {"error": "Unknown action"}


async def test_an_unrecognised_action_name_is_refused():
    out = await _block().process({}, {"action": "explode"})

    assert out == {"error": "Unknown action"}


# -- Signing -------------------------------------------------------------------


async def test_send_signs_the_body_with_hmac_sha256_over_the_configured_secret(
    monkeypatch,
):
    recorder = _Recorder([(200, "")]).install(monkeypatch)
    payload = {"invoice": 7, "amount": "1250.00"}

    out = await _block(secret="s3cr3t").process(
        {"url": "https://hooks.example.com/pay", "payload": payload},
        {"action": "send"},
    )

    assert out == {
        "sent": True,
        "url": "https://hooks.example.com/pay",
        "status": 200,
        "attempt": 1,
    }
    assert len(recorder.posts) == 1
    post = recorder.posts[0]
    assert post["url"] == "https://hooks.example.com/pay"
    assert post["json"] == payload, "the JSON body is the caller's payload verbatim"
    assert post["headers"]["Content-Type"] == "application/json"
    assert post["headers"]["X-Webhook-Signature"] == _expected_signature(
        "s3cr3t", payload
    )
    assert post["headers"]["X-Webhook-Timestamp"].lstrip("-").isdigit()


async def test_signature_is_keyed_by_the_secret_and_bound_to_the_payload(monkeypatch):
    """Change the secret or the body and the signature must change."""
    recorder = _Recorder([(200, "")]).install(monkeypatch)
    payload_a = {"id": 1}
    payload_b = {"id": 2}

    await _block(secret="key-one").process(
        {"url": "https://hooks.example.com/a", "payload": payload_a}, {"action": "send"}
    )
    await _block(secret="key-two").process(
        {"url": "https://hooks.example.com/a", "payload": payload_a}, {"action": "send"}
    )
    await _block(secret="key-one").process(
        {"url": "https://hooks.example.com/a", "payload": payload_b}, {"action": "send"}
    )

    sig_a, sig_other_key, sig_other_body = [
        post["headers"]["X-Webhook-Signature"] for post in recorder.posts
    ]
    assert sig_a == _expected_signature("key-one", payload_a)
    assert sig_a != sig_other_key, "a different secret must not produce the same MAC"
    assert sig_a != sig_other_body, "a different body must not produce the same MAC"
    assert sig_other_key == _expected_signature("key-two", payload_a)


async def test_a_per_call_secret_overrides_the_block_secret(monkeypatch):
    recorder = _Recorder([(200, "")]).install(monkeypatch)
    payload = {"id": 9}

    await _block(secret="block-secret").process(
        {
            "url": "https://hooks.example.com/x",
            "payload": payload,
            "secret": "call-secret",
        },
        {"action": "send"},
    )

    assert recorder.posts[0]["headers"]["X-Webhook-Signature"] == _expected_signature(
        "call-secret", payload
    )


async def test_caller_headers_are_preserved_alongside_the_signature(monkeypatch):
    recorder = _Recorder([(200, "")]).install(monkeypatch)

    await _block().process(
        {
            "url": "https://hooks.example.com/x",
            "payload": {"a": 1},
            "headers": {"X-Tenant": "acme"},
        },
        {"action": "send"},
    )

    headers = recorder.posts[0]["headers"]
    assert headers["X-Tenant"] == "acme"
    assert "X-Webhook-Signature" in headers


# -- SSRF guard ----------------------------------------------------------------


async def test_loopback_target_is_refused_before_a_session_is_opened(monkeypatch):
    recorder = _Recorder().install(monkeypatch)

    out = await _block().process(
        {"url": "http://127.0.0.1:9000/hook", "payload": {"a": 1}}, {"action": "send"}
    )

    assert out["error"].startswith("Unsafe webhook URL:")
    assert "127.0.0.1" in out["error"]
    assert recorder.sessions == 0, "nothing may be dialled once the guard refuses"


async def test_private_host_target_is_refused(monkeypatch):
    recorder = _Recorder().install(monkeypatch)

    out = await _block().process(
        {"url": "http://internal.example.com/hook", "payload": {"a": 1}},
        {"action": "send"},
    )

    assert "non-public address (10.0.0.5)" in out["error"]
    assert recorder.posts == []


async def test_non_http_scheme_target_is_refused(monkeypatch):
    _Recorder().install(monkeypatch)

    out = await _block().process(
        {"url": "ftp://hooks.example.com/hook", "payload": {}}, {"action": "send"}
    )

    assert "Only http/https URLs are allowed" in out["error"]


async def test_redirects_are_disabled_on_the_outbound_post(monkeypatch):
    """The guard checked one host; a 30x must not carry the POST somewhere else."""
    recorder = _Recorder([(200, "")]).install(monkeypatch)

    await _block().process(
        {"url": "https://hooks.example.com/x", "payload": {}}, {"action": "send"}
    )

    assert recorder.posts[0]["kwargs"]["allow_redirects"] is False


# -- Retries -------------------------------------------------------------------


async def test_a_failing_attempt_is_retried_after_exponential_backoff(
    monkeypatch, no_backoff
):
    recorder = _Recorder([(500, "boom"), (200, "")]).install(monkeypatch)

    out = await _block(max_retries=3).process(
        {"url": "https://hooks.example.com/x", "payload": {}}, {"action": "send"}
    )

    assert out["sent"] is True
    assert out["attempt"] == 2
    assert len(recorder.posts) == 2
    assert no_backoff == [1], "2**0 seconds before the second attempt"


async def test_exhausted_retries_report_the_status_and_the_response_body(
    monkeypatch, no_backoff
):
    recorder = _Recorder([(503, "upstream unavailable")]).install(monkeypatch)

    out = await _block(max_retries=3).process(
        {"url": "https://hooks.example.com/x", "payload": {}}, {"action": "send"}
    )

    assert out == {
        "error": "HTTP 503: upstream unavailable",
        "url": "https://hooks.example.com/x",
        "attempts": 3,
    }
    assert len(recorder.posts) == 3
    assert no_backoff == [1, 2], "1s then 2s between the three attempts"


async def test_a_transport_exception_is_retried_then_reported(monkeypatch, no_backoff):
    import aiohttp

    attempts = []

    class _ExplodingSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def post(self, *args, **kwargs):
            attempts.append(1)
            raise ConnectionResetError("peer hung up")

    monkeypatch.setattr(aiohttp, "ClientSession", _ExplodingSession)

    out = await _block(max_retries=2).process(
        {"url": "https://hooks.example.com/x", "payload": {}}, {"action": "send"}
    )

    assert out["error"] == "Failed after 2 attempts: peer hung up"
    assert out["url"] == "https://hooks.example.com/x"
    assert len(attempts) == 2
    assert no_backoff == [1]


async def test_zero_retries_returns_the_guard_message_and_sends_nothing(monkeypatch):
    recorder = _Recorder().install(monkeypatch)

    out = await _block(max_retries=0).process(
        {"url": "https://hooks.example.com/x", "payload": {}}, {"action": "send"}
    )

    assert out == {
        "error": "Webhook not sent — max_retries must be >= 1",
        "url": "https://hooks.example.com/x",
    }
    assert recorder.posts == []


# -- Registration and fan-out --------------------------------------------------


async def test_register_then_list_reports_what_was_stored():
    block = _block()

    registered = await block.process(
        {
            "name": "billing",
            "url": "https://billing.example.com/hook",
            "events": ["payment.received"],
        },
        {"action": "register"},
    )
    assert registered == {
        "registered": True,
        "name": "billing",
        "url": "https://billing.example.com/hook",
        "events": ["payment.received"],
    }

    await block.process(
        {"name": "audit", "url": "https://audit.example.com/hook"},
        {"action": "register"},
    )

    listed = await block.process({}, {"action": "list"})
    assert listed["count"] == 2
    assert listed["webhooks"] == [
        {
            "name": "billing",
            "url": "https://billing.example.com/hook",
            "events": ["payment.received"],
        },
        {
            "name": "audit",
            "url": "https://audit.example.com/hook",
            "events": ["*"],
        },
    ]


async def test_list_is_empty_before_anything_is_registered():
    out = await _block().process({}, {"action": "list"})

    assert out == {"webhooks": [], "count": 0}


async def test_trigger_fans_out_only_to_subscribed_endpoints(monkeypatch):
    recorder = _Recorder([(200, "")]).install(monkeypatch)
    block = _block()
    await block.process(
        {
            "name": "billing",
            "url": "https://billing.example.com/hook",
            "events": ["payment.received"],
        },
        {"action": "register"},
    )
    await block.process(
        {"name": "audit", "url": "https://audit.example.com/hook", "events": ["*"]},
        {"action": "register"},
    )
    await block.process(
        {
            "name": "hooks",
            "url": "https://hooks.example.com/hook",
            "events": ["user.created"],
        },
        {"action": "register"},
    )

    out = await block.process(
        {"event": "user.created", "payload": {"user_id": 41}}, {"action": "trigger"}
    )

    assert out["event"] == "user.created"
    assert out["triggered"] == 2, "billing subscribes to payment.received only"
    assert [r["name"] for r in out["results"]] == ["audit", "hooks"]
    assert all(r["sent"] is True for r in out["results"])
    posted = {post["url"]: post["json"] for post in recorder.posts}
    assert set(posted) == {
        "https://audit.example.com/hook",
        "https://hooks.example.com/hook",
    }
    assert posted["https://audit.example.com/hook"] == {
        "user_id": 41,
        "event": "user.created",
    }, "the event name is merged into the delivered payload"


async def test_trigger_signs_each_delivery_with_that_endpoints_own_secret(monkeypatch):
    recorder = _Recorder([(200, "")]).install(monkeypatch)
    block = _block(secret="block-default")
    await block.process(
        {
            "name": "billing",
            "url": "https://billing.example.com/hook",
            "secret": "billing-key",
        },
        {"action": "register"},
    )
    await block.process(
        {"name": "audit", "url": "https://audit.example.com/hook"},
        {"action": "register"},
    )

    await block.process({"event": "ping", "payload": {"n": 1}}, {"action": "trigger"})

    delivered = {post["url"]: post["headers"]["X-Webhook-Signature"] for post in recorder.posts}
    expected_body = {"n": 1, "event": "ping"}
    assert delivered["https://billing.example.com/hook"] == _expected_signature(
        "billing-key", expected_body
    )
    assert delivered["https://audit.example.com/hook"] == _expected_signature(
        "block-default", expected_body
    ), "an endpoint registered without a secret inherits the block's"


async def test_trigger_with_no_registered_endpoints_delivers_nothing(monkeypatch):
    recorder = _Recorder().install(monkeypatch)

    out = await _block().process(
        {"event": "user.created", "payload": {}}, {"action": "trigger"}
    )

    assert out == {"event": "user.created", "triggered": 0, "results": []}
    assert recorder.sessions == 0


async def test_trigger_reports_a_refused_endpoint_url_per_endpoint(monkeypatch):
    """One bad endpoint is reported in its own row, not raised for the batch."""
    recorder = _Recorder([(200, "")]).install(monkeypatch)
    block = _block()
    await block.process(
        {"name": "inside", "url": "http://internal.example.com/hook"},
        {"action": "register"},
    )
    await block.process(
        {"name": "audit", "url": "https://audit.example.com/hook"},
        {"action": "register"},
    )

    out = await block.process({"event": "ping", "payload": {}}, {"action": "trigger"})

    assert out["triggered"] == 2
    rows = {r["name"]: r for r in out["results"]}
    assert "Unsafe webhook URL" in rows["inside"]["error"]
    assert rows["audit"]["sent"] is True
    assert [post["url"] for post in recorder.posts] == [
        "https://audit.example.com/hook"
    ]


async def test_action_may_arrive_in_the_input_dict(monkeypatch):
    _Recorder([(200, "")]).install(monkeypatch)

    out = await _block().process(
        {
            "action": "send",
            "url": "https://hooks.example.com/x",
            "payload": {"a": 1},
        },
        None,
    )

    assert out["sent"] is True


async def test_health_reports_the_registered_endpoint_count():
    block = _block(max_retries=5)
    await block.process(
        {"name": "audit", "url": "https://audit.example.com/hook"},
        {"action": "register"},
    )

    health = block.health()

    assert health["name"] == "webhook"
    assert health["endpoints"] == 1
    assert health["max_retries"] == 5
