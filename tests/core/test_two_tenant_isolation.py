"""Concurrent two-tenant isolation on the live /v1/execute path.

Two tenants using the same block and the same key names must never see each
other's data — under concurrency, and even if one tries to name the other's
namespace explicitly.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.blocks.memory import MemoryBlock
from app.routers.execute import ExecuteRequest, _run_block


def _auth(key_id: str) -> dict:
    return {"id": key_id, "email": f"{key_id}@example.com", "tier": "pro"}


@pytest.fixture
def memory_env(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    block = MemoryBlock(None, {"max_size": 1000, "default_ttl": 3600})
    patches = [
        patch("app.routers.execute.BLOCK_REGISTRY", {"memory": object}),
        patch("app.routers.execute.get_block_instance", lambda n: block),
        patch("app.routers.execute.adapt_input", lambda d, b: d),
    ]
    for p in patches:
        p.start()
    yield block
    for p in patches:
        p.stop()


async def _set(auth, key, value, extra=None):
    return await _run_block(
        ExecuteRequest(
            block="memory",
            input={"action": "set", "key": key, "value": value, **(extra or {})},
            params={},
        ),
        auth,
    )


async def _get(auth, key, extra=None):
    return await _run_block(
        ExecuteRequest(
            block="memory",
            input={"action": "get", "key": key, **(extra or {})},
            params={},
        ),
        auth,
    )


@pytest.mark.asyncio
async def test_concurrent_tenants_do_not_share_keys(memory_env):
    tenant_a, tenant_b = _auth("tenant-a"), _auth("tenant-b")

    # Concurrent interleaved writes to the SAME key names.
    await asyncio.gather(
        *[_set(tenant_a, f"k{i}", f"a-{i}") for i in range(10)],
        *[_set(tenant_b, f"k{i}", f"b-{i}") for i in range(10)],
    )
    reads_a, reads_b = await asyncio.gather(
        asyncio.gather(*[_get(tenant_a, f"k{i}") for i in range(10)]),
        asyncio.gather(*[_get(tenant_b, f"k{i}") for i in range(10)]),
    )
    for i, (ra, rb) in enumerate(zip(reads_a, reads_b)):
        va = (ra.get("result") or {}).get("value") or ra.get("value")
        vb = (rb.get("result") or {}).get("value") or rb.get("value")
        assert va == f"a-{i}", f"tenant A read {va!r} for k{i}"
        assert vb == f"b-{i}", f"tenant B read {vb!r} — cross-tenant leak"


@pytest.mark.asyncio
async def test_caller_cannot_name_another_tenants_namespace(memory_env):
    tenant_a, tenant_b = _auth("tenant-a"), _auth("tenant-b")
    await _set(tenant_a, "secret", "a-only")

    # Tenant B tries to reach tenant A's namespace explicitly.
    stolen = await _get(
        tenant_b, "secret", extra={"_namespace": "tenant:apikey:tenant-a"}
    )
    value = (stolen.get("result") or {}).get("value") or stolen.get("value")
    assert value != "a-only", "caller-supplied _namespace crossed the tenant boundary"
