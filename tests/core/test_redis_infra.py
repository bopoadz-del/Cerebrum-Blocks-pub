"""Tests for the universal Redis infrastructure module.

No live Redis is required — the shared clients are mocked directly so these
unit tests run anywhere and prove the fail-soft contracts.
"""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import redis_infra, cache_wrapper


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    """Clear singletons and REDIS_URL before/after every test."""
    redis_infra.reset_for_tests()
    monkeypatch.delenv("REDIS_URL", raising=False)
    yield
    redis_infra.reset_for_tests()
    monkeypatch.delenv("REDIS_URL", raising=False)


@pytest.mark.asyncio
async def test_get_redis_client_returns_none_without_url():
    assert await redis_infra.get_redis_client() is None


def test_get_sync_redis_client_returns_none_without_url():
    assert redis_infra.get_sync_redis_client() is None


@pytest.mark.asyncio
async def test_redis_health_reports_disconnected_without_url():
    assert await redis_infra.redis_health() == {"connected": False, "latency_ms": None}


@pytest.mark.asyncio
async def test_get_redis_client_caches_successful_client(monkeypatch):
    fake = AsyncMock()
    fake.ping = AsyncMock(return_value=True)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(
        redis_infra.aioredis, "from_url", MagicMock(return_value=fake)
    )

    client = await redis_infra.get_redis_client()
    assert client is fake
    assert await redis_infra.get_redis_client() is fake
    fake.ping.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_redis_client_returns_none_on_ping_failure(monkeypatch):
    fake = AsyncMock()
    fake.ping = AsyncMock(side_effect=ConnectionError("refused"))
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(
        redis_infra.aioredis, "from_url", MagicMock(return_value=fake)
    )

    assert await redis_infra.get_redis_client() is None


@pytest.mark.asyncio
async def test_redis_health_reports_latency_on_success(monkeypatch):
    fake = AsyncMock()
    fake.ping = AsyncMock(return_value=True)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(
        redis_infra.aioredis, "from_url", MagicMock(return_value=fake)
    )

    health = await redis_infra.redis_health()
    assert health["connected"] is True
    assert isinstance(health["latency_ms"], (int, float))
    assert health["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_close_redis_client_closes_async_client(monkeypatch):
    fake = AsyncMock()
    fake.ping = AsyncMock(return_value=True)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(
        redis_infra.aioredis, "from_url", MagicMock(return_value=fake)
    )
    await redis_infra.get_redis_client()

    await redis_infra.close_redis_client()

    fake.close.assert_awaited_once()
    assert redis_infra._async_client is None


@pytest.mark.asyncio
async def test_cache_round_trip_with_mocked_redis(monkeypatch):
    fake = AsyncMock()
    fake.ping = AsyncMock(return_value=True)
    fake.get = AsyncMock(return_value='{"x": 1}')
    fake.setex = AsyncMock(return_value=True)
    fake.delete = AsyncMock(return_value=1)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(
        redis_infra.aioredis, "from_url", MagicMock(return_value=fake)
    )

    assert await cache_wrapper.cache_get("k") == {"x": 1}
    assert await cache_wrapper.cache_set("k", {"x": 2}) is True
    fake.setex.assert_awaited_once()
    assert await cache_wrapper.cache_delete("k") is True


@pytest.mark.asyncio
async def test_cache_operations_return_false_on_missing_redis():
    assert await cache_wrapper.cache_get("k") is None
    assert await cache_wrapper.cache_set("k", "v") is False
    assert await cache_wrapper.cache_delete("k") is False
