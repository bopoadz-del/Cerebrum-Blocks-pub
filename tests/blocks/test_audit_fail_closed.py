"""audit_fail_closed: donor security-pilot semantics + refusal paths.

Donor: <private-repo> api/audit_middleware.py + api/auth.py; the
header-forgery and persist-failure cases mirror the donor's
tests/test_security_pilot.py.
"""
from __future__ import annotations

import asyncio

import pytest

from app.blocks.audit_fail_closed import (
    AUDIT_FAIL_DETAIL,
    AuditFailClosedBlock,
    Principal,
)


OP_TOKEN = "op-secret-token"
REV_TOKEN = "rev-secret-token"


def _run(coro):
    return asyncio.run(coro)


def _block(**config):
    return AuditFailClosedBlock(config={"operator_token": OP_TOKEN, "reviewer_token": REV_TOKEN, **config})


async def _fake_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"ok"})


def _scope(method="POST", path="/api/x", headers=None):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
    }


async def _call(middleware, scope):
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request"}

    await middleware(scope, receive, send)
    return sent


def test_principal_from_bearer_token():
    b = _block()
    r = _run(b.execute({"action": "principal", "authorization": f"Bearer {OP_TOKEN}"}))
    assert r["status"] == "ok"
    assert r["result"] == {"actor": "operator", "role": "operator"}
    r = _run(b.execute({"action": "principal", "authorization": f"Bearer {REV_TOKEN}"}))
    assert r["result"] == {"actor": "reviewer", "role": "reviewer"}


def test_principal_anonymous_paths():
    b = _block()
    assert _run(b.execute({"action": "principal", "authorization": None}))["result"] == {"actor": "anonymous", "role": "unknown"}
    assert _run(b.execute({"action": "principal", "authorization": "Basic abc"}))["result"]["actor"] == "anonymous"
    assert _run(b.execute({"action": "principal", "authorization": "Bearer wrong"}))["result"]["actor"] == "anonymous"


def test_require_principal_unconfigured_refused():
    b = _block(operator_token="", reviewer_token="")
    r = _run(b.execute({"action": "require_principal", "authorization": f"Bearer {OP_TOKEN}"}))
    assert r["status"] == "refused"
    assert r["error"] == "auth_tokens_not_configured"


def test_require_principal_missing_token_refused():
    b = _block()
    r = _run(b.execute({"action": "require_principal", "authorization": None}))
    assert r["status"] == "refused"
    assert r["error"] == "missing_bearer_token"


def test_require_principal_unknown_token_refused():
    b = _block()
    r = _run(b.execute({"action": "require_principal", "authorization": "Bearer nope"}))
    assert r["status"] == "refused"
    assert r["error"] == "unknown_token"


def test_require_principal_ok():
    b = _block()
    r = _run(b.execute({"action": "require_principal", "authorization": f"Bearer {OP_TOKEN}"}))
    assert r["status"] == "ok"
    assert r["result"]["role"] == "operator"


def test_require_operator_refuses_reviewer():
    b = _block()
    r = _run(b.execute({"action": "require_operator", "authorization": f"Bearer {REV_TOKEN}"}))
    assert r["status"] == "refused"
    assert r["error"] == "operator_role_required"


def test_record_persist_failure_is_failed_envelope():
    b = _block()
    r = _run(b.execute({"action": "record", "actor": "operator", "role": "operator", "method": "POST", "path": "/x", "status_code": 200, "persist_error": True}))
    assert r["status"] == "failed"
    assert "injected persist failure" in r["error"]
    # nothing silently recorded
    assert _run(b.execute({"action": "ledger"}))["result"]["rows"] == []


def test_record_and_ledger_ok():
    b = _block()
    r = _run(b.execute({"action": "record", "actor": "operator", "role": "operator", "method": "POST", "path": "/x", "status_code": 200}))
    assert r["status"] == "ok"
    rows = _run(b.execute({"action": "ledger"}))["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["actor"] == "operator"


def test_middleware_forged_x_actor_ignored():
    # The donor's test_security_pilot.py::test_audit_uses_principal_not_client_headers:
    # a forged x-actor header on a reviewer token must NOT change attribution.
    b = _block()
    middleware = b.make_middleware(_fake_app)
    scope = _scope("POST", "/api/guest", headers=[
        (b"authorization", f"Bearer {REV_TOKEN}".encode()),
        (b"x-actor", b"attacker"),
        (b"x-role", b"operator"),
    ])
    sent = _run(_call(middleware, scope))
    assert sent[0]["status"] == 200
    rows = b._ledger
    assert len(rows) == 1
    assert rows[0]["actor"] == "reviewer"
    assert rows[0]["role"] == "reviewer"


def test_middleware_persist_failure_fails_closed_503():
    # The donor's test_security_pilot.py::test_audit_failure_fail_closed_on_mutating_success:
    # a persist failure on an authenticated mutating 2xx becomes 503.
    b = _block()

    def failing_persist(**kwargs):
        raise RuntimeError("db down")

    middleware = b.make_middleware(_fake_app, persist=failing_persist)
    scope = _scope("POST", "/api/guest", headers=[(b"authorization", f"Bearer {OP_TOKEN}".encode())])
    sent = _run(_call(middleware, scope))
    assert sent[0]["status"] == 503
    body = sent[-1]["body"]
    assert AUDIT_FAIL_DETAIL.encode() in body


def test_middleware_public_path_bypasses_audit():
    b = _block()
    middleware = b.make_middleware(_fake_app)
    scope = _scope("GET", "/health")
    sent = _run(_call(middleware, scope))
    assert sent[0]["status"] == 200
    assert b._ledger == []


def test_middleware_anonymous_mutating_not_held():
    # No bearer -> anonymous -> no hold; 2xx passes through and is audited as anonymous.
    b = _block()
    middleware = b.make_middleware(_fake_app)
    scope = _scope("DELETE", "/api/guest")
    sent = _run(_call(middleware, scope))
    assert sent[0]["status"] == 200
    assert b._ledger[0]["actor"] == "anonymous"


def test_middleware_authenticated_get_not_held():
    b = _block()
    middleware = b.make_middleware(_fake_app)
    scope = _scope("GET", "/api/guest", headers=[(b"authorization", f"Bearer {OP_TOKEN}".encode())])
    sent = _run(_call(middleware, scope))
    assert sent[0]["status"] == 200
    assert b._ledger[0]["actor"] == "operator"


def test_middleware_authenticated_mutating_held_then_released():
    b = _block()
    middleware = b.make_middleware(_fake_app)
    scope = _scope("POST", "/api/guest", headers=[(b"authorization", f"Bearer {OP_TOKEN}".encode())])
    sent = _run(_call(middleware, scope))
    assert [m["type"] for m in sent] == ["http.response.start", "http.response.body"]
    assert sent[0]["status"] == 200
    assert b._ledger[0]["status_code"] == 200


def test_middleware_non_http_scope_passthrough():
    b = _block()
    called = {}

    async def lifespan_app(scope, receive, send):
        called["type"] = scope["type"]

    middleware = b.make_middleware(lifespan_app)
    scope = {"type": "lifespan"}
    sent = _run(_call(middleware, scope))
    assert called["type"] == "lifespan"
    assert sent == []


def test_unknown_action_error():
    b = _block()
    r = _run(b.execute({"action": "forgery_check"}))
    assert r["status"] == "error"
    assert "unknown action" in r["error"]


@pytest.mark.asyncio
async def test_process_is_async_coroutine():
    b = _block()
    r = await b.process({"action": "principal", "authorization": f"Bearer {OP_TOKEN}"})
    assert r["status"] == "ok"
    assert r["result"] == {"actor": "operator", "role": "operator"}
