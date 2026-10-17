"""Isolated-level sandbox execution must use SANDBOX_RUNNER_URL — no in-process fallback.

The in-process restricted exec is a static-blocking convenience for trusted
input, NOT an isolation boundary. Untrusted code (level="isolated") without a
sandbox runner is refused by name; a runner that is configured but
unreachable is refused too — never silently re-executed in-process.

Runs on Windows as well: the refusal paths never touch the Unix `resource`
module, unlike tests/test_sandbox_runner_client.py's in-process exec cases.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest

from app.blocks.sandbox import SandboxBlock


class _FakeResponse:
    def __init__(self, status_code: int = 200, body: Dict[str, Any] | None = None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


def _install_fake_httpx_post(monkeypatch, response: _FakeResponse, calls: list):
    import httpx

    async def fake_post(self, url, *, json=None, **kwargs):
        calls.append({"url": url, "json": json})
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


def _install_failing_httpx_post(monkeypatch, exc: Exception):
    import httpx

    async def fake_post(self, url, *, json=None, **kwargs):
        raise exc

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


def _run(block: SandboxBlock, **data) -> Dict[str, Any]:
    asyncio.run(block._legacy_initialize())
    return asyncio.run(block.process(dict(data), params={"action": "execute"}))


@pytest.fixture(autouse=True)
def _no_runner_env(monkeypatch):
    monkeypatch.delenv("SANDBOX_RUNNER_URL", raising=False)


def test_isolated_without_runner_url_is_refused(monkeypatch):
    """Untrusted code with no runner configured must not execute in-process."""
    block = SandboxBlock()
    out = _run(
        block,
        code="result = 1 + 1",
        language="python",
        level="isolated",
    )
    assert out.get("success") is False
    assert out.get("blocked") is True
    assert "SANDBOX_RUNNER_URL" in out.get("error", "")


def test_isolated_unreachable_runner_is_refused(monkeypatch):
    """A configured-but-unreachable runner is a refusal, never a fallback."""
    import httpx

    monkeypatch.setenv("SANDBOX_RUNNER_URL", "http://127.0.0.1:59999")
    _install_failing_httpx_post(monkeypatch, httpx.ConnectError("refused"))
    block = SandboxBlock()
    out = _run(
        block,
        code="result = 1 + 1",
        language="python",
        level="isolated",
    )
    assert out.get("success") is False
    assert out.get("blocked") is True
    assert "no in-process fallback" in out.get("error", "")


def test_isolated_with_runner_executes_remotely(monkeypatch):
    """With a runner configured, isolated code runs through it."""
    calls = []
    monkeypatch.setenv("SANDBOX_RUNNER_URL", "http://runner.local")
    _install_fake_httpx_post(
        monkeypatch,
        _FakeResponse(200, {"status": "ok", "result": 2, "stdout": "", "stderr": ""}),
        calls,
    )
    block = SandboxBlock()
    out = _run(
        block,
        code="result = 1 + 1",
        language="python",
        level="isolated",
    )
    assert out.get("success") is True
    assert out.get("result") == 2
    assert calls and calls[0]["url"] == "http://runner.local/exec"
    assert calls[0]["json"]["language"] == "python"


def test_isolated_bash_without_runner_url_is_refused(monkeypatch):
    """The allowlist alone is not isolation; isolated bash needs the runner."""
    block = SandboxBlock()
    out = _run(
        block,
        code="echo hello",
        language="bash",
        level="isolated",
    )
    assert out.get("success") is False
    assert out.get("blocked") is True
    assert "SANDBOX_RUNNER_URL" in out.get("error", "")


def test_strict_level_without_runner_still_runs_in_process():
    """The in-process restricted path remains for trusted (non-isolated) code."""
    block = SandboxBlock()
    out = _run(
        block,
        code="result = 6 * 7",
        language="python",
        level="strict",
    )
    assert out.get("success") is True
    assert out.get("result") == 42
