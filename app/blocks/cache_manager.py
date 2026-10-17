"""Cache Manager Block - Redis wrapper with in-memory fallback."""

import json
import time
from typing import Any, Dict, Optional
from app.core.universal_base import UniversalBlock
from app.core.redis_infra import get_sync_redis_client
from app.core.block_config import Config, fallback_note
from app.core.http_errors import error_kind


class CacheManagerBlock(UniversalBlock):
    """Key-value cache with Redis support and local fallback."""

    name = "cache_manager"
    version = "1.0.0"
    description = "Redis wrapper with get/set/delete/stats actions"
    layer = 0
    tags = ["infrastructure", "cache", "redis"]
    requires = []

    default_config = {
        "default_ttl": 3600,
        "max_local_entries": 10000,
    }

    ui_schema = {
        "input": {
            "type": "json",
            "accept": None,
            "placeholder": '{"action": "get", "key": "my-key"}',
            "multiline": False
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "value", "type": "json", "label": "Cached Value"}
            ]
        },
        "quick_actions": [
            {"icon": "📥", "label": "Get Value", "prompt": '{"action":"get","key":"my-key"}'},
            {"icon": "📤", "label": "Set Value", "prompt": '{"action":"set","key":"my-key","value":"my-value","ttl":3600}'},
            {"icon": "🗑️", "label": "Clear Cache", "prompt": '{"action":"clear"}'}
        ]
    }

    def __init__(self, hal_block=None, config=None):
        super().__init__(hal_block, config)
        self._local_cache: Dict[str, Dict] = {}

    @property
    def settings(self) -> Config:
        """The settings this block was HANDED.

        A property rather than an attribute set in ``__init__`` so it cannot
        go stale when a caller edits ``config`` after construction.

        This module calls ``os.getenv`` nowhere. Reference implementation for
        KERNEL_DEFAULTS 1.5 -- see app/core/block_config.py for why.
        """
        return Config(self.config)

    @property
    def _redis(self):
        """The cache client this block was given, or None for the local rung.

        MUST stay a property. It was a plain method while every call site
        used it as an attribute (`if self._redis:` / `self._redis.get`).
        A bound method is always truthy, so the Redis branch was taken even
        with no Redis configured, `.get`/`.setex` raised AttributeError into
        the `except Exception` handlers, and every cache call returned
        {"status": "error"}. The local in-memory fallback was unreachable.
        (#87.)

        Resolution, in order, and all of it injected:

        1. ``redis_client``          -- a client handed straight in. This is
           what makes the Redis-present path testable without a server.
        2. ``cache_backend="memory"`` -- pins the fallback rung, so a zip can
           be told to boot with no services at all.
        3. ``redis_client_factory``  -- defaults to the shared factory, which
           is what an un-configured block used before this change and still
           uses now. That default is the whole non-breaking guarantee.
        """
        client = self.settings.get("redis_client")
        if client is not None:
            return client
        if str(self.settings.backend("cache") or "").lower() in ("memory", "local"):
            return None
        factory = self.settings.get("redis_client_factory") or get_sync_redis_client
        return factory()

    def _rung(self) -> str:
        """Which rung of the ladder this block actually landed on."""
        return "redis" if self._redis is not None else "memory"

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Route to appropriate cache action."""
        params = params or {}
        action = params.get("action") or (input_data.get("action") if isinstance(input_data, dict) else "stats")
        handlers = {
            "get": self.get,
            "set": self.set,
            "delete": self.delete,
            "exists": self.exists,
            "flush": self.flush,
            "stats": self.stats,
            "health_check": self.health_check,
        }
        handler = handlers.get(action)
        if not handler:
            return {"status": "error", "error": f"Unknown action: {action}"}
        return await handler(input_data, params)

    async def get(self, input_data: Any, params: Dict) -> Dict:
        """Retrieve value by key."""
        key, error = self._scoped_key(input_data, params)
        if error:
            return error

        if self._redis is not None:
            try:
                raw = self._redis.get(key)
                if raw is None:
                    return {"status": "success", "found": False, "key": key}
                return {"status": "success", "found": True, "key": key, "value": json.loads(raw)}
            except Exception as e:
                return {"status": "error", "error": str(e), "error_kind": error_kind(e)}

        entry = self._local_cache.get(key)
        if entry is None or entry.get("expires", float("inf")) < time.time():
            return {"status": "success", "found": False, "key": key}
        return {"status": "success", "found": True, "key": key, "value": entry["value"]}

    async def set(self, input_data: Any, params: Dict) -> Dict:
        """Store value by key with optional TTL."""
        key, error = self._scoped_key(input_data, params)
        if error:
            return error

        value = params.get("value") or (input_data.get("value") if isinstance(input_data, dict) else None)
        ttl = params.get("ttl", self.config.get("default_ttl", 3600))

        if self._redis is not None:
            try:
                self._redis.setex(key, ttl, json.dumps(value))
                return {"status": "success", "action": "set", "key": key, "ttl": ttl}
            except Exception as e:
                return {"status": "error", "error": str(e), "error_kind": error_kind(e)}

        # Enforce local limit
        if len(self._local_cache) >= self.config.get("max_local_entries", 10000):
            self._evict_oldest()

        self._local_cache[key] = {"value": value, "expires": time.time() + ttl}
        return {"status": "success", "action": "set", "key": key, "ttl": ttl}

    async def delete(self, input_data: Any, params: Dict) -> Dict:
        """Remove key from cache."""
        key, error = self._scoped_key(input_data, params)
        if error:
            return error

        if self._redis is not None:
            try:
                deleted = self._redis.delete(key)
                return {"status": "success", "deleted": bool(deleted), "key": key}
            except Exception as e:
                return {"status": "error", "error": str(e), "error_kind": error_kind(e)}

        existed = key in self._local_cache
        self._local_cache.pop(key, None)
        return {"status": "success", "deleted": existed, "key": key}

    async def exists(self, input_data: Any, params: Dict) -> Dict:
        """Check if key exists."""
        key, error = self._scoped_key(input_data, params)
        if error:
            return error

        if self._redis is not None:
            try:
                return {"status": "success", "exists": bool(self._redis.exists(key)), "key": key}
            except Exception as e:
                return {"status": "error", "error": str(e), "error_kind": error_kind(e)}

        entry = self._local_cache.get(key)
        exists = entry is not None and entry.get("expires", float("inf")) >= time.time()
        return {"status": "success", "exists": exists, "key": key}

    async def flush(self, input_data: Any = None, params: Dict = None) -> Dict:
        """Clear all cached entries."""
        if self._redis is not None:
            try:
                self._redis.flushdb()
                return {"status": "success", "action": "flush"}
            except Exception as e:
                return {"status": "error", "error": str(e), "error_kind": error_kind(e)}

        count = len(self._local_cache)
        self._local_cache.clear()
        return {"status": "success", "action": "flush", "local_entries_cleared": count}

    async def stats(self, input_data: Any = None, params: Dict = None) -> Dict:
        """Return cache statistics."""
        if self._redis is not None:
            try:
                info = self._redis.info()
                return {
                    "status": "success",
                    "backend": "redis",
                    "keys": self._redis.dbsize(),
                    "used_memory_human": info.get("used_memory_human", "unknown")
                }
            except Exception as e:
                return {"status": "error", "error": str(e), "error_kind": error_kind(e)}

        # Clean expired local entries
        now = time.time()
        valid = {k: v for k, v in self._local_cache.items() if v.get("expires", float("inf")) >= now}
        self._local_cache = valid
        return {
            "status": "success",
            "backend": "local",
            "entries": len(self._local_cache),
            "note": fallback_note("cache", "memory"),
        }

    async def health_check(self, input_data: Any = None, params: Dict = None) -> Dict:
        """Health check for cache manager."""
        rung = self._rung()
        return {
            "status": "success",
            "block": self.name,
            "version": self.version,
            # Unchanged key and meaning; now resolved through the same seam
            # as every other method, so an injected client is not invisible
            # here while it is honoured everywhere else.
            "redis_connected": rung == "redis",
            "backend": rung,
            # Degrading is legitimate. Degrading QUIETLY is not: serving from
            # an in-process dict while the caller believes it is talking to
            # Redis is how a cache works in testing and loses every write in
            # production.
            "note": fallback_note("cache", rung),
        }

    #: Unit separator. A tenant/project/class/key that contains ``:`` or
    #: ``/`` must not be able to collide with another scope by picking a
    #: clever logical key.
    _SCOPE_SEP = "\x1f"

    def scope_key(
        self,
        logical_key: str,
        tenant_id: str,
        project_id: str,
        source_class: str,
    ) -> str:
        """The on-wire cache key. Tenant, project and source class are load-bearing.

        A key that is only the caller's logical name is how tenant A reads
        tenant B's value. The mutation probe in the tests drops ``tenant_id``
        from this formula and shows the leak; this method is the one that
        must not regress to that formula.
        """
        parts = (str(tenant_id), str(project_id), str(source_class), str(logical_key))
        if not all(part.strip() for part in parts):
            raise ValueError(
                "cache scope requires tenant_id, project_id, source_class, and key"
            )
        return self._SCOPE_SEP.join(parts)

    def _scope_fields(self, input_data: Any, params: Dict) -> tuple:
        data = input_data if isinstance(input_data, dict) else {}
        tenant = params.get("tenant_id") or data.get("tenant_id") or self.settings.get("tenant_id")
        project = (
            params.get("project_id")
            or data.get("project_id")
            or self.settings.get("project_id")
        )
        source_class = (
            params.get("source_class")
            or data.get("source_class")
            or self.settings.get("source_class")
        )
        return tenant, project, source_class

    def _resolve_key(self, input_data: Any, params: Dict) -> Optional[str]:
        """Return the scoped key, or None when the logical key is missing.

        Missing scope is not None: it is an error the caller must see.
        Use :meth:`_scoped_key` from action methods.
        """
        key, error = self._scoped_key(input_data, params)
        if error and "No key" in error.get("error", ""):
            return None
        return key

    def _scoped_key(self, input_data: Any, params: Dict) -> tuple:
        logical = params.get("key") or (
            input_data.get("key") if isinstance(input_data, dict) else None
        )
        if not logical:
            return None, {"status": "error", "error": "No key provided"}
        tenant, project, source_class = self._scope_fields(input_data, params)
        if not (tenant and project and source_class):
            return None, {
                "status": "error",
                "error": "Cache scope requires tenant_id, project_id, and source_class",
            }
        return (
            self.scope_key(str(logical), str(tenant), str(project), str(source_class)),
            None,
        )

    def _evict_oldest(self):
        if self._local_cache:
            oldest = min(self._local_cache, key=lambda k: self._local_cache[k]["expires"])
            self._local_cache.pop(oldest, None)

    def get_actions(self) -> Dict[str, Any]:
        """Return all public methods for block registry."""
        return {
            "get": self.get,
            "set": self.set,
            "delete": self.delete,
            "exists": self.exists,
            "flush": self.flush,
            "stats": self.stats,
            "health_check": self.health_check,
        }
