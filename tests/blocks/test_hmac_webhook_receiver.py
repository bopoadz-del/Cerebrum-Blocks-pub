"""Real-behavior tests for the per-source HMAC webhook receiver block."""

import hashlib
import hmac
import time

import pytest

from app.blocks.hmac_webhook_receiver import HmacWebhookReceiverBlock


SECRET = "whsec_test_secret_123"


def _gh_signature(body: str, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _slack_signature(body: str, ts: int, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode(), f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    return f"v0={digest}"


@pytest.mark.asyncio
async def test_github_valid_signature_verified():
    body = '{"event": "push"}'
    env = await HmacWebhookReceiverBlock().execute({
        "action": "verify", "source": "github", "body": body,
        "headers": {"X-Hub-Signature-256": _gh_signature(body)},
        "secret": SECRET,
    })
    assert env["status"] == "ok"
    assert env["result"]["verified"] is True
    assert env["result"]["source"] == "github"


@pytest.mark.asyncio
async def test_github_missing_header_refused():
    env = await HmacWebhookReceiverBlock().execute({
        "action": "verify", "source": "github", "body": "{}",
        "headers": {}, "secret": SECRET,
    })
    assert env["status"] == "refused"
    assert "missing signature header" in env["error"]


@pytest.mark.asyncio
async def test_github_wrong_secret_refused():
    body = "{}"
    env = await HmacWebhookReceiverBlock().execute({
        "action": "verify", "source": "github", "body": body,
        "headers": {"X-Hub-Signature-256": _gh_signature(body, secret="other-secret")},
        "secret": SECRET,
    })
    assert env["status"] == "refused"
    assert "mismatch" in env["error"]


@pytest.mark.asyncio
async def test_github_malformed_prefix_refused():
    env = await HmacWebhookReceiverBlock().execute({
        "action": "verify", "source": "github", "body": "{}",
        "headers": {"X-Hub-Signature-256": "deadbeef"},
        "secret": SECRET,
    })
    assert env["status"] == "refused"
    assert "malformed" in env["error"]


@pytest.mark.asyncio
async def test_slack_valid_signature_verified():
    body = '{"text": "hi"}'
    ts = int(time.time())
    env = await HmacWebhookReceiverBlock().execute({
        "action": "verify", "source": "slack", "body": body,
        "headers": {
            "X-Slack-Signature": _slack_signature(body, ts),
            "X-Slack-Request-Timestamp": str(ts),
        },
        "secret": SECRET,
    })
    assert env["status"] == "ok"
    assert env["result"]["verified"] is True


@pytest.mark.asyncio
async def test_slack_stale_timestamp_refused():
    body = "{}"
    stale_ts = int(time.time()) - 3600
    env = await HmacWebhookReceiverBlock().execute({
        "action": "verify", "source": "slack", "body": body,
        "headers": {
            "X-Slack-Signature": _slack_signature(body, stale_ts),
            "X-Slack-Request-Timestamp": str(stale_ts),
        },
        "secret": SECRET,
    })
    assert env["status"] == "refused"
    assert "replay refused" in env["error"]


@pytest.mark.asyncio
async def test_slack_missing_timestamp_refused():
    body = "{}"
    env = await HmacWebhookReceiverBlock().execute({
        "action": "verify", "source": "slack", "body": body,
        "headers": {"X-Slack-Signature": _slack_signature(body, int(time.time()))},
        "secret": SECRET,
    })
    assert env["status"] == "refused"


@pytest.mark.asyncio
async def test_slack_mismatched_signature_refused():
    body = "{}"
    ts = int(time.time())
    env = await HmacWebhookReceiverBlock().execute({
        "action": "verify", "source": "slack", "body": body,
        "headers": {
            "X-Slack-Signature": _slack_signature("tampered", ts),
            "X-Slack-Request-Timestamp": str(ts),
        },
        "secret": SECRET,
    })
    assert env["status"] == "refused"
    assert "mismatch" in env["error"]


@pytest.mark.asyncio
async def test_procore_valid_signature_verified():
    body = '{"project": "p1"}'
    digest = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    env = await HmacWebhookReceiverBlock().execute({
        "action": "verify", "source": "procore", "body": body,
        "headers": {"X-Procore-Signature": digest},
        "secret": SECRET,
    })
    assert env["status"] == "ok"
    assert env["result"]["verified"] is True


@pytest.mark.asyncio
async def test_procore_mismatched_signature_refused():
    env = await HmacWebhookReceiverBlock().execute({
        "action": "verify", "source": "procore", "body": "{}",
        "headers": {"X-Procore-Signature": "deadbeef"},
        "secret": SECRET,
    })
    assert env["status"] == "refused"
    assert "mismatch" in env["error"]


@pytest.mark.asyncio
async def test_donor_v1_scheme_sign_then_verify_roundtrip():
    block = HmacWebhookReceiverBlock()
    signed = await block.execute({
        "action": "sign",
        "payload": {"a": 1, "b": [2, 3]},
        "secret": SECRET,
    })
    header = signed["result"]["signature_header"]
    env = await block.execute({
        "action": "verify", "source": "maximo",
        "body": {"b": [2, 3], "a": 1},  # order-insensitive canonical JSON
        "headers": {"X-Webhook-Signature": header},
        "secret": SECRET,
    })
    assert env["status"] == "ok"
    assert env["result"]["verified"] is True


@pytest.mark.asyncio
async def test_donor_v1_scheme_tampered_payload_refused():
    block = HmacWebhookReceiverBlock()
    signed = await block.execute({
        "action": "sign", "payload": {"a": 1}, "secret": SECRET,
    })
    header = signed["result"]["signature_header"]
    env = await block.execute({
        "action": "verify", "source": "maximo",
        "body": {"a": 2},
        "headers": {"X-Webhook-Signature": header},
        "secret": SECRET,
    })
    assert env["status"] == "refused"
    assert "mismatch" in env["error"]


@pytest.mark.asyncio
async def test_donor_v1_scheme_stale_timestamp_refused():
    block = HmacWebhookReceiverBlock()
    stale = int(time.time()) - 3600
    signed = await block.execute({
        "action": "sign", "payload": {"a": 1}, "secret": SECRET, "timestamp": stale,
    })
    env = await block.execute({
        "action": "verify", "source": "maximo",
        "body": {"a": 1},
        "headers": {"X-Webhook-Signature": signed["result"]["signature_header"]},
        "secret": SECRET,
    })
    assert env["status"] == "refused"
    assert "replay refused" in env["error"]


@pytest.mark.asyncio
async def test_donor_v1_scheme_malformed_header_refused():
    env = await HmacWebhookReceiverBlock().execute({
        "action": "verify", "source": "cerebrum",
        "body": {"a": 1},
        "headers": {"X-Webhook-Signature": "not-a-valid-header"},
        "secret": SECRET,
    })
    assert env["status"] == "refused"
    assert "invalid signature header" in env["error"]


@pytest.mark.asyncio
async def test_missing_secret_refused():
    env = await HmacWebhookReceiverBlock().execute({
        "action": "verify", "source": "github", "body": "{}",
        "headers": {"X-Hub-Signature-256": "sha256=aa"}, "secret": "",
    })
    assert env["status"] == "refused"
    assert "secret is required" in env["error"]


@pytest.mark.asyncio
async def test_missing_body_refused():
    env = await HmacWebhookReceiverBlock().execute({
        "action": "verify", "source": "github",
        "headers": {"X-Hub-Signature-256": "sha256=aa"}, "secret": SECRET,
    })
    assert env["status"] == "refused"


@pytest.mark.asyncio
async def test_unknown_source_refused():
    env = await HmacWebhookReceiverBlock().execute({
        "action": "verify", "source": "zendesk", "body": "{}",
        "headers": {}, "secret": SECRET,
    })
    assert env["status"] == "refused"
    assert "unknown webhook source" in env["error"]


@pytest.mark.asyncio
async def test_schemes_lists_all_sources():
    env = await HmacWebhookReceiverBlock().execute({"action": "schemes"})
    assert env["status"] == "ok"
    assert set(env["result"]["sources"]) == {"github", "slack", "procore", "maximo", "cerebrum"}


@pytest.mark.asyncio
async def test_generate_secret_prefixed():
    env = await HmacWebhookReceiverBlock().execute({"action": "generate_secret"})
    assert env["status"] == "ok"
    assert env["result"]["secret"].startswith("whsec_")


@pytest.mark.asyncio
async def test_sign_requires_secret_and_dict_payload():
    block = HmacWebhookReceiverBlock()
    env = await block.execute({"action": "sign", "payload": {"a": 1}})
    assert env["status"] == "refused"
    env = await block.execute({"action": "sign", "secret": SECRET, "payload": "not-a-dict"})
    assert env["status"] == "error"
