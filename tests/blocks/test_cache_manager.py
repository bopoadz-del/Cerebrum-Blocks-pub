"""Tests for the cache manager block — Redis and local-fallback paths.

Harvested from The_Fork (tests/blocks/test_cache_manager.py). Three layout
differences between the two repos are adapted here; none of them weaken an
assertion:

1. **Client seam.** The_Fork's block awaits a module-level async singleton
   (``app.core.redis_client.get_redis_client``). The Store's block resolves a
   *synchronous* client through an injected seam
   (``settings["redis_client"]`` / ``settings["redis_client_factory"]``,
   defaulting to ``app.core.redis_infra.get_sync_redis_client``). The fakes
   below are therefore sync, and are injected rather than monkeypatched.
2. **Scoped keys.** The Store's block refuses an unscoped key: every
   operation requires ``tenant_id``, ``project_id`` and ``source_class``, and
   the on-wire key is ``scope_key(...)``, not the caller's logical name. The
   Fork has no such requirement. The assertions below carry the scope through
   and check the on-wire key really is the scoped one.
3. **Backend pinning.** ``cache_backend="memory"`` is the Store's documented
   way to pin the local rung, replacing the Fork's "unset REDIS_URL" fixture.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from app.blocks.cache_manager import CacheManagerBlock


# ── Scope every block under test ────────────────────────────────────────────

SCOPE = {
    "tenant_id": "t1",
    "project_id": "p1",
    "source_class": "unit-test",
}


def _local_block(**extra) -> CacheManagerBlock:
    """A block pinned to the in-memory rung (no Redis, no services)."""
    return CacheManagerBlock(config={"cache_backend": "memory", **SCOPE, **extra})


def _redis_block(client, **extra) -> CacheManagerBlock:
    """A block handed a cache client directly — the documented test seam."""
    return CacheManagerBlock(config={"redis_client": client, **SCOPE, **extra})


# ── Fake sync Redis backends ────────────────────────────────────────────────


class _FakeRedis:
    """Minimal sync Redis implementation backed by an in-memory dict."""

    def __init__(self):
        self._store: Dict[str, str] = {}

    def get(self, key: str):
        return self._store.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    def delete(self, key: str) -> int:
        return 1 if self._store.pop(key, None) is not None else 0

    def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    def flushdb(self) -> None:
        self._store.clear()

    def info(self) -> Dict[str, Any]:
        return {"used_memory_human": "1M"}

    def dbsize(self) -> int:
        return len(self._store)


class _FailingFakeRedis:
    """Always raises. Exercises the block's error path on a live-but-broken
    cache."""

    def get(self, key: str) -> Any:
        raise Exception("Redis unavailable")

    def setex(self, key: str, ttl: int, value: str) -> Any:
        raise Exception("Redis unavailable")

    def delete(self, key: str) -> Any:
        raise Exception("Redis unavailable")

    def exists(self, key: str) -> Any:
        raise Exception("Redis unavailable")

    def flushdb(self) -> Any:
        raise Exception("Redis unavailable")

    def info(self) -> Any:
        raise Exception("Redis unavailable")

    def dbsize(self) -> Any:
        raise Exception("Redis unavailable")


# ── Local-fallback tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_local_set_get_delete_exists_flush_stats():
    block = _local_block()
    wire = block.scope_key("k1", **{"tenant_id": "t1", "project_id": "p1",
                                    "source_class": "unit-test"})

    set_r = await block.set({}, {"key": "k1", "ttl": 3600, "value": "v1"})
    assert set_r["status"] == "success"
    assert set_r["action"] == "set"
    assert set_r["ttl"] == 3600
    # The on-wire key is scoped, never the caller's bare logical name.
    assert set_r["key"] == wire
    assert set_r["key"] != "k1"

    get_r = await block.get({}, {"key": "k1"})
    assert get_r["status"] == "success"
    assert get_r["found"] is True
    assert get_r["value"] == "v1"

    assert await block.exists({}, {"key": "k1"}) == {
        "status": "success",
        "exists": True,
        "key": wire,
    }

    assert await block.delete({}, {"key": "k1"}) == {
        "status": "success",
        "deleted": True,
        "key": wire,
    }

    assert await block.exists({}, {"key": "k1"}) == {
        "status": "success",
        "exists": False,
        "key": wire,
    }

    flush_r = await block.flush()
    assert flush_r["status"] == "success"
    assert flush_r["action"] == "flush"
    assert flush_r["local_entries_cleared"] == 0

    stats = await block.stats()
    assert stats["status"] == "success"
    assert stats["backend"] == "local"
    assert stats["entries"] == 0


@pytest.mark.asyncio
async def test_a_value_written_under_one_tenant_is_not_readable_by_another():
    """The scope is load-bearing, not decoration: same logical key, two
    tenants, two values. This is the assertion The_Fork's suite could not
    make."""
    a = CacheManagerBlock(config={"cache_backend": "memory", "tenant_id": "A",
                                  "project_id": "p1", "source_class": "c"})
    b = CacheManagerBlock(config={"cache_backend": "memory", "tenant_id": "B",
                                  "project_id": "p1", "source_class": "c"})
    # Both blocks share nothing; prove the KEYS differ, which is what stops
    # a shared Redis from leaking across tenants.
    assert a.scope_key("shared", "A", "p1", "c") != b.scope_key("shared", "B", "p1", "c")

    client = _FakeRedis()
    a_redis = _redis_block(client)
    b_redis = CacheManagerBlock(config={"redis_client": client, "tenant_id": "B",
                                        "project_id": "p1", "source_class": "c"})
    await a_redis.set({}, {"key": "shared", "value": "tenant-A-secret"})
    found = await b_redis.get({}, {"key": "shared"})
    assert found["found"] is False, "tenant B read tenant A's cache entry"


@pytest.mark.asyncio
async def test_missing_key_returns_error():
    block = _local_block()

    for action in ("get", "set", "delete", "exists"):
        result = await block.process({}, {"action": action})
        assert result["status"] == "error"
        assert "No key provided" in result["error"]


@pytest.mark.asyncio
async def test_missing_scope_is_an_error_not_a_silent_global_key():
    """An unscoped call must fail loudly. A block that quietly writes to a
    global key is how tenant A reads tenant B's value."""
    block = CacheManagerBlock(config={"cache_backend": "memory"})
    result = await block.process({}, {"action": "set", "key": "k", "value": 1})
    assert result["status"] == "error"
    assert "scope" in result["error"].lower()


@pytest.mark.asyncio
async def test_process_routes_actions_and_unknown_action():
    block = _local_block()

    set_r = await block.process({"key": "p1", "value": "x"}, {"action": "set"})
    assert set_r["status"] == "success"

    get_r = await block.process({"key": "p1"}, {"action": "get"})
    assert get_r["status"] == "success"
    assert get_r["value"] == "x"

    health = await block.process({}, {"action": "health_check"})
    assert health["status"] == "success"
    assert health["redis_connected"] is False

    unknown = await block.process({}, {"action": "nope"})
    assert unknown["status"] == "error"
    assert "Unknown action" in unknown["error"]


# ── Injected cache-client tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_backend_roundtrip():
    """When a cache client is available, the block uses it."""
    fake = _FakeRedis()
    block = _redis_block(fake)

    set_r = await block.set({}, {"key": "r1", "value": {"a": 1}, "ttl": 60})
    assert set_r["status"] == "success"
    # It really went to the client, not to the local dict.
    assert len(fake._store) == 1
    assert block._local_cache == {}

    get_r = await block.get({}, {"key": "r1"})
    assert get_r["found"] is True
    assert get_r["value"] == {"a": 1}

    exists_r = await block.exists({}, {"key": "r1"})
    assert exists_r["exists"] is True

    delete_r = await block.delete({}, {"key": "r1"})
    assert delete_r["deleted"] is True

    assert (await block.exists({}, {"key": "r1"}))["exists"] is False

    stats = await block.stats()
    assert stats["backend"] == "redis"
    assert stats["keys"] == 0
    assert stats["used_memory_human"] == "1M"

    health = await block.health_check()
    assert health["redis_connected"] is True


@pytest.mark.asyncio
async def test_redis_error_is_reported_not_silently_absorbed():
    """A live-but-broken cache must surface as an error.

    CONTRACT DIVERGENCE, recorded rather than smoothed over: The_Fork's block
    swallows the exception and serves from a local dict, so the caller cannot
    tell a cache hit from a cache outage. The Store's block returns
    ``{"status": "error"}`` instead — the fail-loud rung documented in
    app/core/block_config.py ("degrading is legitimate; degrading quietly is
    not"). This test asserts the Store's contract; The_Fork's
    ``test_redis_error_falls_back_to_local`` asserts the opposite and is
    deliberately NOT carried across.
    """
    block = _redis_block(_FailingFakeRedis())

    for call in (
        block.set({}, {"key": "f1", "value": "fv", "ttl": 60}),
        block.get({}, {"key": "f1"}),
        block.exists({}, {"key": "f1"}),
        block.delete({}, {"key": "f1"}),
        block.flush(),
        block.stats(),
    ):
        result = await call
        assert result["status"] == "error"
        assert "Redis unavailable" in result["error"]

    # And nothing leaked into the local dict behind the caller's back.
    assert block._local_cache == {}


@pytest.mark.asyncio
async def test_flushdb_called_when_redis_available():
    fake = _FakeRedis()
    fake._store["x"] = "1"
    block = _redis_block(fake)

    flush_r = await block.flush()
    assert flush_r["status"] == "success"
    assert flush_r["action"] == "flush"
    assert fake._store == {}


@pytest.mark.asyncio
async def test_health_check_names_the_rung_it_landed_on():
    """A cache that silently degrades to an in-process dict loses every write
    in production. The block must say which rung it is on."""
    local = await _local_block().health_check()
    assert local["backend"] == "memory"
    assert local["redis_connected"] is False
    assert "memory" in local["note"]

    remote = await _redis_block(_FakeRedis()).health_check()
    assert remote["backend"] == "redis"
    assert remote["redis_connected"] is True
