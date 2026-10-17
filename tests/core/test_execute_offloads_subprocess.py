"""Registry-subprocess execution must not block the event loop.

`_run_block` falls back to `_run_registry_block` for registry-only blocks,
which calls ``subprocess.run(..., timeout=60)``. Run synchronously on the
event loop, that froze every other request — including the /health liveness
probe Render polls continuously — for up to 60 seconds. The fix offloads the
subprocess call to a worker thread (``anyio.to_thread.run_sync``), the same
pattern as the pre-warm offload in ``app/dependencies.py::init_blocks``.

These tests drive the real ASGI app with a fake ``subprocess.run`` that
sleeps 1.5s: /health must answer well before the registry block finishes,
and the registry response envelope must match the previous sync path.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path

import httpx
import pytest

import app.routers.execute as execute_mod
from app.core.block_capabilities import BlockCapabilities

_BLOCK = "offload_probe_block"
_FAKE_OUTPUT = {"echo": "offloaded"}
_SUBPROCESS_SLEEP_S = 1.5


class _FakeCompletedProcess:
    returncode = 0
    stdout = json.dumps({"success": True, "output": _FAKE_OUTPUT})
    stderr = ""


@pytest.fixture
def registry_probe_block(monkeypatch):
    """Register a throwaway registry-only block whose subprocess is a sleep.

    The adapter file must exist on disk (``_run_registry_block`` checks the
    path before spawning), but it is never executed: ``subprocess.run`` is
    replaced with a fake that sleeps and returns a canned success payload.
    """
    project_root = Path(execute_mod.__file__).resolve().parents[2]
    block_dir = project_root / "block_registry" / _BLOCK
    block_dir.mkdir(parents=True, exist_ok=True)
    (block_dir / "block.json").write_text(
        json.dumps(
            {
                "id": _BLOCK,
                "permissions": {
                    "network": False,
                    "filesystem": False,
                    "imports": [],
                    "blocks": [],
                },
            }
        ),
        encoding="utf-8",
    )
    (block_dir / "block.py").write_text(
        'raise SystemExit("test adapter — never meant to actually run")\n',
        encoding="utf-8",
    )

    def _fake_subprocess_run(*args, **kwargs):
        time.sleep(_SUBPROCESS_SLEEP_S)
        return _FakeCompletedProcess()

    monkeypatch.setattr(execute_mod.subprocess, "run", _fake_subprocess_run)
    # Unknown non-core publishers resolve to community tier (sandboxed);
    # pin safe reviewed capabilities so the in-process registry path runs.
    monkeypatch.setattr(
        execute_mod,
        "get_block_capabilities",
        lambda name: BlockCapabilities(publisher_tier="reviewed"),
    )
    try:
        yield
    finally:
        shutil.rmtree(block_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_health_stays_responsive_while_registry_block_executes(registry_probe_block):
    """/health must answer while the registry subprocess is still running."""
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": "Bearer cb_dev_key"},
    ) as client:
        started = time.monotonic()
        execute_task = asyncio.create_task(
            client.post(
                "/v1/execute",
                json={"block": _BLOCK, "input": {"x": 1}, "params": {}},
            )
        )
        # Give the execute request time to reach the (fake) subprocess.
        await asyncio.sleep(0.2)

        health_resp = await client.get("/health")
        health_elapsed = time.monotonic() - started

        assert health_resp.status_code == 200
        assert health_resp.json().get("status") == "ok"
        # With the old sync path the loop is frozen for the full 1.5s sleep
        # and /health cannot answer until the subprocess returns.
        assert health_elapsed < 1.0, (
            f"/health took {health_elapsed:.2f}s — event loop blocked by "
            "the registry subprocess"
        )
        # The registry block must genuinely still be in flight off-loop.
        assert not execute_task.done()

        execute_resp = await execute_task

    assert execute_resp.status_code == 200


@pytest.mark.asyncio
async def test_offloaded_registry_result_matches_sync_contract(registry_probe_block):
    """The worker-thread path returns the exact envelope the sync path did."""
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": "Bearer cb_dev_key"},
    ) as client:
        resp = await client.post(
            "/v1/execute",
            json={"block": _BLOCK, "input": {"x": 1}, "params": {}},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["block"] == _BLOCK
    assert body["status"] == "success"
    assert body["result"] == _FAKE_OUTPUT
    assert body["source_id"] == f"{_BLOCK}-registry"
    assert body["metadata"]["source"] == "registry"
