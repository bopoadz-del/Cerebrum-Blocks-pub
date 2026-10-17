"""Notification block: real outbound delivery, signed over the bytes sent.

Fixtures are real socket servers bound to 127.0.0.1 in-test, not mocked
clients:

* an HTTP sink (``http.server.ThreadingHTTPServer``) that records the raw
  request body and headers of every POST and answers a scripted status
  sequence, so a 500-then-200 retry is observed on the wire;
* a raw-socket SMTP sink that speaks enough ESMTP (220/250/354/221) for
  stdlib ``smtplib`` to complete a session, and keeps the DATA bytes.

The HMAC key is minted per test with ``secrets.token_hex`` -- nothing
credential-shaped is committed. Every assertion is on a value
``NotificationBlock.process`` computed: the delivery record it returned, the
bytes the sink received, and the signature the sink recomputed over those
bytes with the same key.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.blocks.notification import NotificationBlock
from app.core.url_guard import UnsafeURLError, validate_outbound_url

MESSAGE = "Pump P-101 tripped on high vibration"
PAYLOAD = {"asset": "P-101", "vibration_mm_s": 12.7, "limit_mm_s": 7.1}


# ── HTTP sink ───────────────────────────────────────────────────────────────


class HttpSink:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.requests = []
        sink = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                sink.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                status = sink.statuses.pop(0) if sink.statuses else 200
                reply = b'{"ok":true}' if status < 400 else b'{"ok":false}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *args):  # keep pytest output clean
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/hook"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def http_sink():
    sinks = []

    def make(statuses=(200,)):
        sink = HttpSink(statuses)
        sinks.append(sink)
        return sink

    yield make
    for sink in sinks:
        sink.close()


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("NOTIFY_WEBHOOK_URL", "NOTIFY_WEBHOOK_SECRET", "NOTIFY_WEBHOOK_ALLOW_PRIVATE",
                 "SMTP_URL", "NOTIFY_SMTP_TO", "NOTIFY_SMTP_FROM"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _block():
    # zero backoff: retries are asserted by count on the wire, not waited out
    return NotificationBlock(None, {"webhook_retry_backoff": 0, "smtp_retry_backoff": 0})


async def _send(block, **data):
    return await block.process({"channel": "webhook", "message": MESSAGE, "event": "alarm", "payload": PAYLOAD, **data},
                               {"action": "send"})


# ── webhook: roundtrip + signature over the received bytes ─────────────────


async def test_webhook_roundtrip_signature_verifies_over_received_bytes(clean_env, http_sink):
    sink = http_sink([200])
    secret = secrets.token_hex(16)
    clean_env.setenv("NOTIFY_WEBHOOK_URL", sink.url)
    clean_env.setenv("NOTIFY_WEBHOOK_SECRET", secret)
    clean_env.setenv("NOTIFY_WEBHOOK_ALLOW_PRIVATE", "1")

    before = int(time.time())
    result = await _send(_block())

    assert result["status"] == "success", result
    assert result["channel"] == "webhook" and result["sent"] is True
    assert result["http_status"] == 200
    record = result["delivery"]
    assert record["mode"] == "live" and record["delivered"] is True
    assert record["attempts"] == 1 and record["signed"] is True
    assert record["url_source"] == "env:NOTIFY_WEBHOOK_URL"
    assert record["target"] == sink.url
    assert record["id"] == result["message_id"]

    assert len(sink.requests) == 1
    req = sink.requests[0]
    raw = req["body"]
    assert record["bytes"] == len(raw)

    # The receiver recomputes HMAC over exactly the bytes it received.
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    assert req["headers"]["X-Cerebrum-Signature"] == f"sha256={expected}"

    envelope = json.loads(raw)
    assert envelope["message"] == MESSAGE
    assert envelope["event"] == "alarm"
    assert envelope["payload"] == PAYLOAD
    assert envelope["id"] == result["message_id"] == req["headers"]["X-Cerebrum-Delivery-Id"]
    assert envelope["channel"] == "webhook"
    assert req["headers"]["Content-Type"].startswith("application/json")

    # Wall-clock UTC seconds: a monotonic loop reading would be seconds since
    # boot, nowhere near the epoch.
    ts = int(req["headers"]["X-Cerebrum-Timestamp"])
    assert before <= ts <= int(time.time()) + 1


async def test_webhook_retries_on_500_then_delivers(clean_env, http_sink):
    sink = http_sink([500, 200])
    secret = secrets.token_hex(16)
    clean_env.setenv("NOTIFY_WEBHOOK_URL", sink.url)
    clean_env.setenv("NOTIFY_WEBHOOK_SECRET", secret)
    clean_env.setenv("NOTIFY_WEBHOOK_ALLOW_PRIVATE", "1")

    result = await _send(_block())
    assert result["status"] == "success" and result["sent"] is True
    assert result["delivery"]["attempts"] == 2
    assert result["delivery"]["delivered"] is True
    assert len(sink.requests) == 2
    # Same bytes, same signature on every attempt.
    assert sink.requests[0]["body"] == sink.requests[1]["body"]
    assert sink.requests[0]["headers"]["X-Cerebrum-Signature"] == sink.requests[1]["headers"]["X-Cerebrum-Signature"]
    assert sink.requests[0]["headers"]["X-Cerebrum-Signature"] == "sha256=" + hmac.new(
        secret.encode(), sink.requests[1]["body"], hashlib.sha256
    ).hexdigest()


async def test_webhook_gives_up_after_two_retries_and_says_so(clean_env, http_sink):
    sink = http_sink([500, 503, 500])
    clean_env.setenv("NOTIFY_WEBHOOK_URL", sink.url)
    clean_env.setenv("NOTIFY_WEBHOOK_ALLOW_PRIVATE", "1")

    result = await _send(_block())
    assert result["status"] == "error" and result["sent"] is False
    assert result["delivery"]["attempts"] == 3
    assert result["delivery"]["delivered"] is False
    assert result["delivery"]["http_status"] == 500
    assert "3 attempt(s)" in result["error"] and "HTTP 500" in result["error"]
    assert len(sink.requests) == 3


async def test_webhook_does_not_retry_a_client_error(clean_env, http_sink):
    sink = http_sink([404])
    clean_env.setenv("NOTIFY_WEBHOOK_URL", sink.url)
    clean_env.setenv("NOTIFY_WEBHOOK_ALLOW_PRIVATE", "1")

    result = await _send(_block())
    assert result["status"] == "error"
    assert result["delivery"]["attempts"] == 1
    assert len(sink.requests) == 1


async def test_webhook_unsigned_when_no_secret_is_declared(clean_env, http_sink):
    sink = http_sink([200])
    clean_env.setenv("NOTIFY_WEBHOOK_URL", sink.url)
    clean_env.setenv("NOTIFY_WEBHOOK_ALLOW_PRIVATE", "1")

    result = await _send(_block())
    assert result["status"] == "success"
    assert result["delivery"]["signed"] is False
    assert "X-Cerebrum-Signature" not in sink.requests[0]["headers"]


# ── no URL: declared outbox, never a silent success ─────────────────────────


async def test_webhook_without_url_lands_in_declared_outbox(clean_env):
    block = _block()
    result = await _send(block)
    assert result["status"] == "outbox"
    assert result["channel"] == "webhook" and result["sent"] is False
    record = result["delivery"]
    assert record["mode"] == "outbox" and record["delivered"] is False
    assert record["attempts"] == 0 and record["target"] is None
    assert "NOTIFY_WEBHOOK_URL" in record["reason"]
    assert "nothing left the process" in result["note"]

    listed = await block.process({"action": "outbox"}, {"action": "outbox"})
    assert listed["count"] == 1
    assert listed["entries"][0]["id"] == result["message_id"]
    assert listed["entries"][0]["channel"] == "webhook"
    assert listed["entries"][0]["event"] == "alarm"

    health = block.process.__self__._health_check()
    assert health["delivery"]["webhook"] == "outbox"
    assert health["delivery"]["outbox_size"] == 1


# ── SSRF guard: operator seam is explicit, caller URLs never get it ─────────


async def test_operator_loopback_url_requires_explicit_allow(clean_env, http_sink):
    sink = http_sink([200])
    clean_env.setenv("NOTIFY_WEBHOOK_URL", sink.url)  # no NOTIFY_WEBHOOK_ALLOW_PRIVATE

    result = await _send(_block())
    assert result["status"] == "error"
    assert "unsafe webhook url" in result["error"]
    assert "env:NOTIFY_WEBHOOK_URL" in result["error"]
    assert sink.requests == []


async def test_caller_url_never_inherits_the_operator_allowance(clean_env, http_sink):
    sink = http_sink([200])
    clean_env.setenv("NOTIFY_WEBHOOK_ALLOW_PRIVATE", "1")
    clean_env.setenv("NOTIFY_WEBHOOK_URL", sink.url)

    result = await _send(_block(), url=sink.url)  # caller-supplied
    assert result["status"] == "error"
    assert "unsafe webhook url (caller)" in result["error"]
    assert sink.requests == []


def test_metadata_range_refused_even_with_operator_allowance():
    with pytest.raises(UnsafeURLError):
        validate_outbound_url("http://169.254.169.254/latest/meta-data/", allow_private_hosts=True)
    with pytest.raises(UnsafeURLError):
        validate_outbound_url("http://0.0.0.0/", allow_private_hosts=True)
    with pytest.raises(UnsafeURLError):
        validate_outbound_url("ftp://127.0.0.1/", allow_private_hosts=True)
    assert validate_outbound_url("http://127.0.0.1:9/x", allow_private_hosts=True) == "http://127.0.0.1:9/x"
    with pytest.raises(UnsafeURLError):
        validate_outbound_url("http://127.0.0.1:9/x")  # the caller rule is unchanged


# ── SMTP sink ───────────────────────────────────────────────────────────────


class SmtpSink:
    """Minimal ESMTP responder on a raw socket. Records each session."""

    def __init__(self, fail_first: int = 0):
        self.fail_first = fail_first
        self.sessions = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self._stop = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        self.sock.settimeout(0.2)
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        with conn:
            if self.fail_first > 0:
                self.fail_first -= 1
                conn.sendall(b"421 sink busy, try again\r\n")
                self.sessions.append({"lines": [], "data": None, "refused": True})
                return
            f = conn.makefile("rb")
            conn.sendall(b"220 sink ESMTP\r\n")
            lines, data = [], None
            while True:
                line = f.readline()
                if not line:
                    break
                lines.append(line)
                cmd = line.strip().upper()
                if cmd.startswith(b"EHLO"):
                    conn.sendall(b"250-sink\r\n250 8BITMIME\r\n")
                elif cmd.startswith(b"HELO"):
                    conn.sendall(b"250 sink\r\n")
                elif cmd.startswith((b"MAIL", b"RCPT", b"NOOP", b"RSET")):
                    conn.sendall(b"250 OK\r\n")
                elif cmd.startswith(b"DATA"):
                    conn.sendall(b"354 End data with <CR><LF>.<CR><LF>\r\n")
                    chunks = []
                    while True:
                        dl = f.readline()
                        if not dl or dl == b".\r\n":
                            break
                        chunks.append(dl)
                    data = b"".join(chunks)
                    conn.sendall(b"250 OK queued as 1\r\n")
                elif cmd.startswith(b"QUIT"):
                    conn.sendall(b"221 bye\r\n")
                    break
                else:
                    conn.sendall(b"500 unsupported\r\n")
            self.sessions.append({"lines": lines, "data": data, "refused": False})

    def close(self):
        self._stop = True
        self.thread.join(timeout=1)
        self.sock.close()


@pytest.fixture
def smtp_sink():
    sinks = []

    def make(fail_first=0):
        sink = SmtpSink(fail_first)
        sinks.append(sink)
        return sink

    yield make
    for sink in sinks:
        sink.close()


async def _send_smtp(block, **data):
    return await block.process({"channel": "smtp", "message": MESSAGE, "event": "alarm", "payload": PAYLOAD,
                                "subject": "P-101 alarm", **data}, {"action": "send"})


async def test_smtp_roundtrip_over_real_socket(clean_env, smtp_sink):
    sink = smtp_sink()
    clean_env.setenv("SMTP_URL", f"smtp://127.0.0.1:{sink.port}?from=alerts%40plant.test")
    clean_env.setenv("NOTIFY_SMTP_TO", "ops@plant.test")

    result = await _send_smtp(_block())
    assert result["status"] == "success", result
    assert result["channel"] == "smtp" and result["sent"] is True
    record = result["delivery"]
    assert record["mode"] == "live" and record["delivered"] is True
    assert record["attempts"] == 1 and record["tls"] is False and record["authenticated"] is False
    assert record["recipients"] == ["ops@plant.test"] and record["refused"] == {}
    assert record["target"] == f"smtp://127.0.0.1:{sink.port}"

    for _ in range(50):
        if any(s["data"] for s in sink.sessions):
            break
        time.sleep(0.02)
    session = [s for s in sink.sessions if s["data"]][0]
    transcript = b"".join(session["lines"]).decode().lower()  # smtplib sends "mail FROM:"
    assert "mail from:<alerts@plant.test>" in transcript
    assert "rcpt to:<ops@plant.test>" in transcript
    assert "auth" not in transcript
    data = session["data"].decode()
    assert "Subject: P-101 alarm" in data
    assert f"X-Cerebrum-Delivery-Id: {result['message_id']}" in data
    assert "X-Cerebrum-Event: alarm" in data
    assert MESSAGE in data
    assert '"asset": "P-101"' in data  # the same envelope the webhook carries


async def test_smtp_retries_a_transient_refusal(clean_env, smtp_sink):
    sink = smtp_sink(fail_first=1)
    clean_env.setenv("SMTP_URL", f"smtp://127.0.0.1:{sink.port}")

    result = await _send_smtp(_block(), to="ops@plant.test")
    assert result["status"] == "success", result
    assert result["delivery"]["attempts"] == 2
    for _ in range(50):
        if len(sink.sessions) >= 2:
            break
        time.sleep(0.02)
    assert [s["refused"] for s in sink.sessions] == [True, False]


async def test_smtp_never_sends_credentials_without_tls(clean_env, smtp_sink):
    sink = smtp_sink()
    password = secrets.token_hex(8)
    clean_env.setenv("SMTP_URL", f"smtp://relay:{password}@127.0.0.1:{sink.port}")

    result = await _send_smtp(_block(), to="ops@plant.test")
    assert result["status"] == "error"
    assert result["delivery"]["delivered"] is False
    assert result["delivery"]["attempts"] == 1  # a policy refusal is not retried
    assert "without TLS" in result["error"]
    for _ in range(50):
        if sink.sessions:
            break
        time.sleep(0.02)
    transcript = b"".join(sink.sessions[0]["lines"]).decode().lower()
    assert "auth" not in transcript and password not in transcript


async def test_smtp_without_url_lands_in_declared_outbox(clean_env):
    block = _block()
    result = await _send_smtp(block)
    assert result["status"] == "outbox" and result["sent"] is False
    assert result["delivery"]["mode"] == "outbox"
    assert "SMTP_URL" in result["delivery"]["reason"]
    listed = await block.process({"action": "outbox"}, {"action": "outbox"})
    assert listed["count"] == 1 and listed["entries"][0]["channel"] == "smtp"


async def test_broadcast_reports_live_and_outbox_per_channel(clean_env, http_sink):
    sink = http_sink([200])
    clean_env.setenv("NOTIFY_WEBHOOK_URL", sink.url)
    clean_env.setenv("NOTIFY_WEBHOOK_ALLOW_PRIVATE", "1")
    result = await _block().process(
        {"channels": ["webhook", "smtp"], "message": MESSAGE, "event": "alarm", "payload": PAYLOAD},
        {"action": "broadcast"},
    )
    assert result["status"] == "partial"
    by_channel = {r["channel"]: r for r in result["results"]}
    assert by_channel["webhook"]["status"] == "success" and by_channel["webhook"]["delivery"]["delivered"] is True
    assert by_channel["smtp"]["status"] == "outbox" and by_channel["smtp"]["delivery"]["delivered"] is False
    assert len(sink.requests) == 1
