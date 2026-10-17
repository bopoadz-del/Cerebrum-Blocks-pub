"""Tests for the SANDBOX_RUNNER_URL wiring in code/sandbox/formula_executor
blocks, plus a smoke test for the runner FastAPI app itself.

These tests don't require the runner container to be deployed; httpx is
patched in-process. The runner's own /health and /exec endpoints are
exercised via FastAPI's TestClient against the imported `server.app`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Unix-only 'resource' module required by app.blocks.sandbox",
)


# ── Helpers ──────────────────────────────────────────────────────────────


class _FakeResponse:
    """Stand-in for httpx.Response."""

    def __init__(self, status_code: int = 200, body: Dict[str, Any] | None = None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


def _install_fake_httpx_post(monkeypatch, response: _FakeResponse, calls: list):
    """Patch httpx.AsyncClient.post to record the call and return `response`."""
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


# ── code.py wiring ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_code_block_uses_runner_when_env_set(monkeypatch):
    monkeypatch.setenv("SANDBOX_RUNNER_URL", "http://runner:8001")
    calls: list = []
    _install_fake_httpx_post(
        monkeypatch,
        _FakeResponse(200, {
            "status": "ok",
            "result": 42,
            "stdout": "hello\n",
            "stderr": "",
            "elapsed_ms": 5,
            "exit_code": 0,
            "timed_out": False,
        }),
        calls,
    )

    from app.blocks.code import CodeBlock
    block = CodeBlock()
    res = await block.process("print('hello')", {"language": "python"})

    assert len(calls) == 1, "should have POSTed exactly once"
    assert calls[0]["url"] == "http://runner:8001/exec"
    assert calls[0]["json"]["language"] == "python"
    assert calls[0]["json"]["code"] == "print('hello')"
    assert res["status"] == "success"
    assert res["result"] == 42
    assert res["output"] == "hello\n"


@pytest.mark.asyncio
async def test_code_block_inprocess_when_env_unset(monkeypatch):
    monkeypatch.delenv("SANDBOX_RUNNER_URL", raising=False)
    calls: list = []
    _install_fake_httpx_post(monkeypatch, _FakeResponse(200, {}), calls)

    from app.blocks.code import CodeBlock
    block = CodeBlock()
    res = await block.process("x = 1", {"language": "python"})

    assert calls == [], "no httpx call should have been made"
    assert res["status"] in ("success", "error")  # in-process runs


@pytest.mark.asyncio
async def test_code_block_falls_back_on_network_error(monkeypatch):
    monkeypatch.setenv("SANDBOX_RUNNER_URL", "http://runner:8001")
    import httpx
    _install_failing_httpx_post(monkeypatch, httpx.ConnectError("boom"))

    from app.blocks.code import CodeBlock
    block = CodeBlock()
    res = await block.process("x = 2 + 2", {"language": "python"})

    # Falls back to in-process — must be a sensible result, not a 500.
    assert "status" in res
    assert res["status"] in ("success", "error")
    assert "error" not in res or res["status"] == "error"


# ── sandbox.py wiring ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sandbox_block_python_uses_runner(monkeypatch):
    monkeypatch.setenv("SANDBOX_RUNNER_URL", "http://runner:8001")
    calls: list = []
    _install_fake_httpx_post(
        monkeypatch,
        _FakeResponse(200, {
            "status": "ok",
            "result": 7,
            "stdout": "",
            "stderr": "",
            "elapsed_ms": 3,
            "exit_code": 0,
            "timed_out": False,
        }),
        calls,
    )

    from app.blocks.sandbox import SandboxBlock
    block = SandboxBlock()
    await block._legacy_initialize()
    res = await block._execute_sandboxed({
        "code": "result = 7",
        "language": "python",
        "inputs": {},
    })

    assert len(calls) == 1
    assert calls[0]["url"] == "http://runner:8001/exec"
    assert res["success"] is True
    assert res["result"] == 7
    assert res.get("runner") is True


@pytest.mark.asyncio
async def test_sandbox_block_bash_uses_runner_after_allowlist(monkeypatch):
    monkeypatch.setenv("SANDBOX_RUNNER_URL", "http://runner:8001")
    calls: list = []
    _install_fake_httpx_post(
        monkeypatch,
        _FakeResponse(200, {
            "status": "ok",
            "result": None,
            "stdout": "hi\n",
            "stderr": "",
            "elapsed_ms": 2,
            "exit_code": 0,
            "timed_out": False,
        }),
        calls,
    )

    from app.blocks.sandbox import SandboxBlock
    block = SandboxBlock()
    await block._legacy_initialize()
    # 'echo' is in the allowlist; safety check should pass.
    res = await block._execute_sandboxed({
        "code": "echo hi",
        "language": "bash",
    })

    # Either the runner was hit, or the safety check blocked it (it shouldn't).
    assert res.get("blocked") is not True
    assert len(calls) == 1
    assert calls[0]["json"]["language"] == "bash"
    assert res["stdout"] == "hi\n"


@pytest.mark.asyncio
async def test_sandbox_block_falls_back_on_runner_error(monkeypatch):
    monkeypatch.setenv("SANDBOX_RUNNER_URL", "http://runner:8001")
    import httpx
    _install_failing_httpx_post(monkeypatch, httpx.ConnectError("nope"))

    from app.blocks.sandbox import SandboxBlock
    block = SandboxBlock()
    await block._legacy_initialize()
    res = await block._execute_sandboxed({
        "code": "result = 1 + 1",
        "language": "python",
    })

    # Falls back to in-process exec; must return a dict, not raise.
    assert isinstance(res, dict)
    assert "success" in res or "error" in res


# ── formula_executor.py wiring ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_formula_executor_custom_code_uses_runner(monkeypatch):
    monkeypatch.setenv("SANDBOX_RUNNER_URL", "http://runner:8001")
    calls: list = []
    _install_fake_httpx_post(
        monkeypatch,
        _FakeResponse(200, {
            "status": "ok",
            "result": 12.5,
            "stdout": "",
            "stderr": "",
            "elapsed_ms": 4,
            "exit_code": 0,
            "timed_out": False,
        }),
        calls,
    )

    from app.blocks.formula_executor import FormulaExecutorBlock
    block = FormulaExecutorBlock()
    res = await block.process({
        "custom_code": "result = 2.5 * 5",
        "input_values": {},
        "formula_description": "compute area in m²",
    })

    assert len(calls) == 1
    assert calls[0]["url"] == "http://runner:8001/exec"
    assert res["status"] == "success"
    assert res["execution_result"] == 12.5
    # Pint validation still ran on the runner-produced result.
    assert "unit_validated_output" in res


@pytest.mark.asyncio
async def test_formula_executor_library_stays_inprocess_even_with_runner(monkeypatch):
    """Library formulas are trusted; SANDBOX_RUNNER_URL must not redirect them."""
    monkeypatch.setenv("SANDBOX_RUNNER_URL", "http://runner:8001")
    calls: list = []
    _install_fake_httpx_post(monkeypatch, _FakeResponse(200, {}), calls)

    from app.blocks.formula_executor import FormulaExecutorBlock
    block = FormulaExecutorBlock()
    res = await block.process({
        "formula_key": "concrete_volume_slab",
        "input_values": {"length_m": 10, "width_m": 8, "thickness_m": 0.2},
    })

    assert calls == [], "library formula must not POST to runner"
    assert res["status"] == "success"
    assert res["execution_result"] == pytest.approx(16.0)


@pytest.mark.asyncio
async def test_formula_executor_falls_back_on_runner_error(monkeypatch):
    monkeypatch.setenv("SANDBOX_RUNNER_URL", "http://runner:8001")
    import httpx
    _install_failing_httpx_post(monkeypatch, httpx.ConnectError("dead"))

    from app.blocks.formula_executor import FormulaExecutorBlock
    block = FormulaExecutorBlock()
    res = await block.process({
        "custom_code": "result = 5 + 5",
        "input_values": {},
    })

    # Should fall back to in-process exec successfully.
    assert res["status"] == "success"
    assert res["execution_result"] == 10


# ── runner server.py direct tests ────────────────────────────────────────


def _load_runner_module():
    """Import sandbox-runner/server.py as a module despite the dash in the
    directory name (which is not a valid Python identifier)."""
    here = Path(__file__).resolve().parent.parent
    server_path = here / "sandbox-runner" / "server.py"
    if not server_path.exists():
        return None
    mod_name = "sandbox_runner_server"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, server_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec so pydantic's forward-ref
    # resolution can find ExecRequest by qualname.
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(mod_name, None)
        return None
    # Force model rebuild after the module fully exists.
    try:
        mod.ExecRequest.model_rebuild()
        mod.ExecResponse.model_rebuild()
    except Exception:
        pass
    return mod


@pytest.fixture(scope="module")
def runner_client():
    """Direct-against-ASGI test of the runner module.

    Skipped by default: pairing this fixture's TestClient with the
    main-app TestClient in tests/test_metrics_endpoint.py deadlocks
    pytest under the same process. To run them, set
    SANDBOX_RUNNER_DIRECT_TESTS=1 (and run only this file or skip the
    metrics test file in the same invocation).
    """
    if not os.getenv("SANDBOX_RUNNER_DIRECT_TESTS"):
        pytest.skip(
            "Runner-direct TestClient tests deadlock with main-app TestClient "
            "in the same process. Set SANDBOX_RUNNER_DIRECT_TESTS=1 to enable."
        )
    mod = _load_runner_module()
    if mod is None:
        pytest.skip("sandbox-runner/server.py not importable")
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi.testclient unavailable")
    return TestClient(mod.app)


def test_runner_health_endpoint(runner_client):
    resp = runner_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_runner_exec_python_returns_result(runner_client):
    resp = runner_client.post("/exec", json={
        "language": "python",
        "code": "result = 6 * 7",
        "input_values": {},
        "timeout_s": 5,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["result"] == 42


def test_runner_exec_rejects_empty_code(runner_client):
    resp = runner_client.post("/exec", json={
        "language": "python",
        "code": "",
        "input_values": {},
        "timeout_s": 5,
    })
    assert resp.status_code == 400


def test_runner_exec_python_uses_input_values(runner_client):
    resp = runner_client.post("/exec", json={
        "language": "python",
        "code": "result = a + b",
        "input_values": {"a": 3, "b": 4},
        "timeout_s": 5,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["result"] == 7
