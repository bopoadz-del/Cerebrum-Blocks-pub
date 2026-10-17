"""Universal Redis infrastructure — shared clients, health, lifecycle.

Env-driven by REDIS_URL. If unset or unreachable, all factories return None
and callers fall back to their existing local behavior. Designed to be copied
or imported into any Cerebrum platform.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import redis
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_async_client: Optional[aioredis.Redis] = None
_sync_client: Optional[redis.Redis] = None


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "").strip()


async def get_redis_client() -> Optional[aioredis.Redis]:
    """Return the shared async Redis client, or None if not configured/unreachable."""
    global _async_client
    if _async_client is not None:
        return _async_client
    url = _redis_url()
    if not url:
        return None
    try:
        _async_client = aioredis.from_url(url, decode_responses=True)
        await _async_client.ping()
    except Exception as exc:
        logger.warning("Redis async client unavailable (%s); fallbacks active", exc)
        _async_client = None
    return _async_client


def get_sync_redis_client() -> Optional[redis.Redis]:
    """Return the shared sync Redis client, or None if not configured/unreachable."""
    global _sync_client
    if _sync_client is not None:
        return _sync_client
    url = _redis_url()
    if not url:
        return None
    try:
        _sync_client = redis.from_url(url, decode_responses=True)
        _sync_client.ping()
    except Exception as exc:
        logger.warning("Redis sync client unavailable (%s); fallbacks active", exc)
        _sync_client = None
    return _sync_client


async def close_redis_client() -> None:
    """Close both shared clients and clear singletons. Safe to call repeatedly."""
    global _async_client, _sync_client
    if _async_client is not None:
        try:
            await _async_client.close()
        except Exception as exc:
            logger.debug("Redis async close failed: %s", exc)
        _async_client = None
    if _sync_client is not None:
        try:
            _sync_client.close()
        except Exception as exc:
            logger.debug("Redis sync close failed: %s", exc)
        _sync_client = None


async def redis_health() -> dict[str, Any]:
    """Probe Redis and return connected status + latency."""
    client = await get_redis_client()
    if client is None:
        return {"connected": False, "latency_ms": None}
    start = time.perf_counter()
    try:
        await client.ping()
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {"connected": True, "latency_ms": latency_ms}
    except Exception as exc:
        logger.warning("Redis health ping failed: %s", exc)
        return {"connected": False, "latency_ms": None}


def reset_for_tests() -> None:
    """Drop singleton clients. Tests must call this to avoid state leakage."""
    global _async_client, _sync_client
    _async_client = None
    _sync_client = None
