# Universal Redis Infrastructure Module

**Repo:** Cerebrum-Blocks  
**Date:** 2026-07-28  
**Scope:** Single reusable Redis layer for Cerebrum-Blocks, <private-repo>, The_Fork, and future platforms.

---

## 1. Goal

Provide one drop-in Redis module that any Cerebrum platform can import. It consolidates connection management, health probing, caching, and (later) job-queue wiring behind a small, stable API. The module is env-driven (`REDIS_URL`) and degrades gracefully when Redis is unset or unreachable.

## 2. Non-goals

- No change to LLM provider logic.
- No new managed-service requirement; URL-driven only.
- No removal of existing in-memory/file fallbacks in consumers.
- arq worker queue is out of scope for this first cut (The_Fork already owns the design; this module will leave an extension point).

## 3. Architectural overview

```
┌─────────────────────────────────────────┐
│           Platform (any repo)           │
│  ┌─────────┐ ┌─────────┐ ┌───────────┐ │
│  │ blocks  │ │ routers │ │  workers  │ │
│  └────┬────┘ └────┬────┘ └─────┬─────┘ │
│       └───────────┴────────────┘        │
│              app.core.redis_infra       │
│         (async + sync factories)        │
│       ┌─────────────────────────┐       │
│       │   app.core.cache_wrapper │      │
│       │  (thin get/set/delete)   │      │
│       └─────────────────────────┘       │
└─────────────────────────────────────────┘
                     │ REDIS_URL
                     ▼
                  Redis
```

## 4. API surface

### 4.1 `app/core/redis_infra.py`

```python
async def get_redis_client() -> Optional[aioredis.Redis]
def get_sync_redis_client() -> Optional[redis.Redis]
async def close_redis_client() -> None
async def redis_health() -> dict[str, Any]
def reset_for_tests() -> None
```

Behavior:
- Singleton clients; lazily initialized on first call.
- `REDIS_URL` unset → returns `None` immediately.
- Ping on first connect; on failure log warning, set client to `None`, return `None`.
- `close_redis_client()` closes both async and sync clients and clears singletons.
- `redis_health()` returns `{"connected": bool, "latency_ms": float|None}`.
- `reset_for_tests()` clears singletons for test isolation.

### 4.2 `app/core/cache_wrapper.py`

```python
async def cache_get(key: str) -> Optional[Any]
async def cache_set(key: str, value: Any, ttl: int = 3600) -> bool
async def cache_delete(key: str) -> bool
```

Behavior:
- JSON-serialized values; `default=str` for non-JSON types.
- Silently returns `None`/`False` if Redis is unavailable.
- Honest: no hidden fallback store; callers that need local fallback implement it themselves.

## 5. Reuse strategy

| Platform | How it uses the module |
|---|---|
| Cerebrum-Blocks | Replace ad-hoc Redis in `cache_manager.py`; add health to `/health`. |
| <private-repo> | Replace per-module `redis.from_url()` in `change_requests/queue.py`, `rate_limit.py`, `factory_drive.py`; replace `_probe_redis()` in `main.py`. |
| The_Fork | Already has equivalent code; this module becomes the upstream copy that The_Fork can sync from. |
| Future platforms | Copy `app/core/redis_infra.py` + `cache_wrapper.py` or import from a shared package. |

## 6. Testing

- Unit tests mock the Redis client at `app.core.redis_infra._async_client` and `_sync_client`.
- Tests cover: URL unset, ping failure, successful health, cache round-trip, close lifecycle, reset seam.
- No live Redis required for unit tests.

## 7. Success criteria

- [ ] `app/core/redis_infra.py` exists with all exported functions.
- [ ] `app/core/cache_wrapper.py` exists with get/set/delete.
- [ ] `tests/core/test_redis_infra.py` passes without a live Redis.
- [ ] `app/blocks/cache_manager.py` uses `get_sync_redis_client()` instead of its own `redis.from_url()`.
- [ ] App boots with `REDIS_URL` unset.

## 8. Revertibility

One commit: `feat(core): universal Redis infrastructure module`. Revert with `git revert <sha>`.
