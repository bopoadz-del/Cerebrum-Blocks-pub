from __future__ import annotations

import json
from unittest import mock
from typing import Any

import httpx
import pytest

from cerebrum_cli import config, main


class _MockStreamContext:
    """Makes a mock httpx response usable as a context manager."""

    def __init__(self, response: httpx.Response):
        self._response = response

    def __enter__(self):
        return self._response

    def __exit__(self, *args):
        return False


class _MockClient:
    """Minimal httpx.Client mock that records stream() calls."""

    def __init__(self, response: httpx.Response):
        self._response = response
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def stream(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return _MockStreamContext(self._response)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _sse_response(payloads: list[dict[str, Any]]) -> httpx.Response:
    body = "".join(f'data: {json.dumps(p)}\n' for p in payloads)
    return httpx.Response(
        200,
        content=body.encode(),
        headers={"content-type": "text/event-stream"},
    )


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    return path


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for key in (
        "CEREBRUM_BASE_URL",
        "CEREBRUM_API_KEY",
        "CEREBRUM_DOMAIN",
        "CEREBRUM_INSTANCE_NAME",
        "CEREBRUM_SESSION_ID",
        "CEREBRUM_MODE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_chat_configurator_mode_uses_session_endpoint(cfg_path, monkeypatch, capsys):
    cfg_path.write_text('api_key = "ak"\nsession_id = "sess_123"\n')
    response = _sse_response([{"type": "end"}])
    client = _MockClient(response)
    monkeypatch.setattr(main, "_client", lambda: client)

    main.main(["chat", "hello"])

    assert len(client.calls) == 1
    args, kwargs = client.calls[0]
    assert args[0] == "POST"
    assert args[1] == "http://127.0.0.1:8000/v1/sessions/sess_123/chat"
    assert kwargs["json"] == {"message": "hello"}


def test_chat_deployed_mode_uses_deployed_endpoint(cfg_path, monkeypatch, capsys):
    cfg_path.write_text('api_key = "ak"\nmode = "deployed"\n')
    response = _sse_response([{"type": "end"}])
    client = _MockClient(response)
    monkeypatch.setattr(main, "_client", lambda: client)

    main.main(["chat", "hello"])

    assert len(client.calls) == 1
    args, kwargs = client.calls[0]
    assert args[0] == "POST"
    assert args[1] == "http://127.0.0.1:8000/v1/deployed/chat"
    assert kwargs["json"] == {"message": "hello", "history": []}


def test_chat_deployed_mode_ignores_session_id(cfg_path, monkeypatch, capsys):
    cfg_path.write_text('api_key = "ak"\nmode = "deployed"\nsession_id = "sess_ignored"\n')
    response = _sse_response([{"type": "end"}])
    client = _MockClient(response)
    monkeypatch.setattr(main, "_client", lambda: client)

    main.main(["--session", "sess_ignored", "chat", "hello"])

    args, kwargs = client.calls[0]
    assert "sessions" not in args[1]
    assert args[1] == "http://127.0.0.1:8000/v1/deployed/chat"


def test_chat_missing_mode_defaults_to_configurator(cfg_path, monkeypatch, capsys):
    cfg_path.write_text('api_key = "ak"\nsession_id = "sess_123"\n')
    response = _sse_response([{"type": "end"}])
    client = _MockClient(response)
    monkeypatch.setattr(main, "_client", lambda: client)

    main.main(["chat", "hello"])

    args, kwargs = client.calls[0]
    assert args[1] == "http://127.0.0.1:8000/v1/sessions/sess_123/chat"


def test_chat_mode_flag_overrides_config(cfg_path, monkeypatch, capsys):
    cfg_path.write_text('api_key = "ak"\nsession_id = "sess_123"\nmode = "configurator"\n')
    response = _sse_response([{"type": "end"}])
    client = _MockClient(response)
    monkeypatch.setattr(main, "_client", lambda: client)

    main.main(["--mode", "deployed", "chat", "hello"])

    args, kwargs = client.calls[0]
    assert args[1] == "http://127.0.0.1:8000/v1/deployed/chat"


def test_config_show_displays_mode(cfg_path, monkeypatch, capsys):
    cfg_path.write_text('api_key = "ak"\nmode = "deployed"\n')

    main.main(["config"])

    captured = capsys.readouterr()
    displayed = json.loads(captured.out)
    assert displayed["mode"] == "deployed"
