"""Tests for the canonical SSE envelope on chat streaming endpoints."""

import json
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import require_api_key
from app.routers import chat as chat_router


async def _no_auth():
    return {"valid": True}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(chat_router.router, dependencies=[])
    # Swap the auth dependency for a no-op so tests don't need real keys.
    for route in app.routes:
        if hasattr(route, "dependencies"):
            route.dependencies = []
    app.dependency_overrides[require_api_key] = _no_auth
    return TestClient(app)


async def _word_stream(words):
    for word in words:
        yield word + " "


def _parse_events(response):
    events = []
    for line in response.iter_lines():
        line = line.decode() if isinstance(line, bytes) else line
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        events.append(json.loads(payload))
    return events


def test_chat_stream_emits_canonical_envelope(client, monkeypatch):
    async def fake_execute(message, params):
        return {
            "result": {
                "stream": _word_stream(["Hello", "world"]),
            }
        }

    monkeypatch.setattr("app.routers.chat.BLOCK_REGISTRY", {"chat": mock.Mock()})
    monkeypatch.setattr("app.routers.chat.block_instances", {"chat": mock.Mock(execute=fake_execute)})

    response = client.post("/chat/stream", json={"message": "hi", "model": "test"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")

    events = _parse_events(response)
    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert types[-1] == "end"
    assert all(t in chat_router.VALID_ENVELOPE_TYPES for t in types)

    tokens = [e["content"] for e in events if e["type"] == "token"]
    assert "".join(tokens) == "Hello world "


def test_v1_chat_stream_emits_canonical_envelope(client, monkeypatch):
    async def fake_execute(message, params):
        return {
            "result": {
                "stream": _word_stream(["yes"]),
            }
        }

    monkeypatch.setattr("app.routers.chat.BLOCK_REGISTRY", {"chat": mock.Mock()})
    monkeypatch.setattr("app.routers.chat.block_instances", {"chat": mock.Mock(execute=fake_execute)})

    response = client.post("/v1/chat/stream", json={"message": "ok", "session_id": "sess_x"})
    assert response.status_code == 200
    events = _parse_events(response)
    assert events[0]["type"] == "start"
    assert events[0].get("session_id") == "sess_x"
    assert events[-1]["type"] == "end"


def test_chat_stream_passes_through_tool_events(client, monkeypatch):
    async def _tool_stream():
        yield {"type": "tool_call", "name": "search", "arguments": {"q": "x"}}
        yield {"type": "tool_result", "name": "search", "status": "ok"}
        yield "result"

    async def fake_execute(message, params):
        return {"result": {"stream": _tool_stream()}}

    monkeypatch.setattr("app.routers.chat.BLOCK_REGISTRY", {"chat": mock.Mock()})
    monkeypatch.setattr("app.routers.chat.block_instances", {"chat": mock.Mock(execute=fake_execute)})

    response = client.post("/chat/stream", json={"message": "hi"})
    events = _parse_events(response)
    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "tool_result" in types
    assert types[-1] == "end"


def test_chat_stream_error_path_terminates_with_error(client, monkeypatch):
    async def _bad_stream():
        raise RuntimeError("boom")
        yield "never"

    async def fake_execute(message, params):
        return {"result": {"stream": _bad_stream()}}

    monkeypatch.setattr("app.routers.chat.BLOCK_REGISTRY", {"chat": mock.Mock()})
    monkeypatch.setattr("app.routers.chat.block_instances", {"chat": mock.Mock(execute=fake_execute)})

    response = client.post("/chat/stream", json={"message": "hi"})
    events = _parse_events(response)
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "error"
    assert "boom" in events[-1].get("message", "")


def test_chat_stream_legacy_error_string(client, monkeypatch):
    async def _legacy_error_stream():
        yield '{"type": "error", "message": "legacy fail"}'

    async def fake_execute(message, params):
        return {"result": {"stream": _legacy_error_stream()}}

    monkeypatch.setattr("app.routers.chat.BLOCK_REGISTRY", {"chat": mock.Mock()})
    monkeypatch.setattr("app.routers.chat.block_instances", {"chat": mock.Mock(execute=fake_execute)})

    response = client.post("/chat/stream", json={"message": "hi"})
    events = _parse_events(response)
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "error"
    assert events[-1]["message"] == "legacy fail"
    # No end after error.
    assert [e["type"] for e in events].count("end") == 0
