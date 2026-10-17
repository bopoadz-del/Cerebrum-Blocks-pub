"""Neutral sliding-window rate limiter with in-memory and optional Redis backends."""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional


class RateLimitError(Exception):
    """Raised when the rate limiter encounters an unrecoverable configuration error."""


class RateLimitBackend:
    """Abstract rate-limit backend."""

    def record_and_check(
        self,
        identity: str,
        action: str,
        window_seconds: float,
        max_requests: int,
        now: float,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError


class InMemoryBackend(RateLimitBackend):
    """Thread-safe in-memory sliding-window backend."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: Dict[str, Deque[float]] = {}

    def record_and_check(
        self,
        identity: str,
        action: str,
        window_seconds: float,
        max_requests: int,
        now: float,
    ) -> Dict[str, Any]:
        key = f"{identity}:{action}"
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = self._buckets[key] = deque()
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= max_requests:
                reset_at = bucket[0] + window_seconds if bucket else now + window_seconds
                return {
                    "allowed": False,
                    "remaining": 0,
                    "reset_at": reset_at,
                }

            bucket.append(now)
            remaining = max_requests - len(bucket)
            reset_at = bucket[0] + window_seconds if bucket else now + window_seconds

            # Best-effort stale bucket pruning.
            if len(self._buckets) > 5000:
                stale = [
                    k
                    for k, b in self._buckets.items()
                    if not b or b[-1] < cutoff
                ]
                for k in stale:
                    self._buckets.pop(k, None)

            return {
                "allowed": True,
                "remaining": remaining,
                "reset_at": reset_at,
            }

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


class RedisBackend(RateLimitBackend):
    """Optional Redis sorted-set sliding-window backend."""

    _PREFIX = "ratelimit:"

    _SLIDING_WINDOW_LUA = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local limit = tonumber(ARGV[3])
    redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
    local count = redis.call('ZCARD', key)
    if count >= limit then
        return 0
    end
    redis.call('ZADD', key, now, tostring(now) .. ':' .. ARGV[4])
    redis.call('EXPIRE', key, math.ceil(window) + 1)
    return 1
    """

    def __init__(self, redis_url: str) -> None:
        import redis  # lazy optional import

        self._client = redis.from_url(redis_url, decode_responses=True)
        self._script = self._client.register_script(self._SLIDING_WINDOW_LUA)

    def record_and_check(
        self,
        identity: str,
        action: str,
        window_seconds: float,
        max_requests: int,
        now: float,
    ) -> Dict[str, Any]:
        key = f"{self._PREFIX}{identity}:{action}"
        try:
            allowed = self._script(
                keys=[key],
                args=[now, window_seconds, max_requests, action],
            )
            if allowed:
                # Approximate remaining using ZCARD after insertion.
                count = self._client.zcard(key)
                remaining = max(0, max_requests - count)
                oldest = self._client.zrange(key, 0, 0, withscores=True)
                reset_at = (oldest[0][1] + window_seconds) if oldest else now + window_seconds
                return {
                    "allowed": True,
                    "remaining": remaining,
                    "reset_at": reset_at,
                }
            oldest = self._client.zrange(key, 0, 0, withscores=True)
            reset_at = (oldest[0][1] + window_seconds) if oldest else now + window_seconds
            return {
                "allowed": False,
                "remaining": 0,
                "reset_at": reset_at,
            }
        except Exception as exc:
            # Redis failures are treated as configuration errors; callers may decide
            # whether to fail open. This kit fails closed by raising.
            raise RateLimitError(f"redis backend failed: {exc}") from exc

    def reset(self) -> None:
        pass


class RateLimiter:
    """Neutral rate limiter with pluggable backend."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        backend: Optional[RateLimitBackend] = None,
    ) -> None:
        if backend is not None:
            self._backend = backend
        else:
            self._backend = self._resolve_backend(redis_url)

    @staticmethod
    def _resolve_backend(redis_url: Optional[str]) -> RateLimitBackend:
        url = (redis_url or os.getenv("RATE_LIMIT_REDIS_URL", "")).strip()
        if url:
            try:
                return RedisBackend(url)
            except Exception:
                pass
        return InMemoryBackend()

    def record_and_check(
        self,
        identity: str,
        action: str,
        window_seconds: float = 60.0,
        max_requests: int = 100,
    ) -> Dict[str, Any]:
        """Record a request and return allowance metadata.

        Returns ``{allowed: bool, remaining: int, reset_at: float}``.
        """
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        now = time.time()
        return self._backend.record_and_check(
            identity, action, window_seconds, max_requests, now
        )

    def reset(self) -> None:
        self._backend.reset()


# Module-level default limiter.
_default_limiter = RateLimiter()


def reset_rate_limiter() -> None:
    """Reset the module-level rate limiter (tests only)."""
    _default_limiter.reset()


def record_and_check(
    identity: str,
    action: str,
    window_seconds: float = 60.0,
    max_requests: int = 100,
) -> Dict[str, Any]:
    """Record a request and return allowance metadata."""
    return _default_limiter.record_and_check(
        identity, action, window_seconds, max_requests
    )
