from app.core.universal_base import UniversalBlock
from typing import Dict, Any, Optional, List
import time
import asyncio
from collections import OrderedDict, defaultdict

# Delimiter that cannot appear in a namespace or user key, avoiding collisions
# when namespaces themselves contain colons (e.g. "system:chat").
_NS_SEP = "\x00"


class MemoryBlock(UniversalBlock):
    """
    High-Speed Memory Cache Block - TTL, LRU eviction, session storage
    Acts as Redis alternative for edge/local deployments.

    Namespace-aware: every instance operates inside a single namespace by
    default ("global"). Multiple instances/proxies can share the same backing
    cache while remaining logically isolated.
    """

    name = "memory"
    version = "1.0.0"
    requires = ["config"]
    layer = 1  # Security/Session layer
    tags = ["security", "cache", "infrastructure"]
    default_config = {
        "max_size": 10000,
        "default_ttl": 3600,
        "cleanup_interval": 300
    }

    ui_schema = {
        'input': {'type': 'json', 'accept': None, 'placeholder': 'Cache key/value payload, e.g. {"key": "session", "value": {...}}', 'multiline': True},
        'output': {'type': 'json', 'fields': [{'name': 'result', 'type': 'json', 'label': 'Result'}]},
        'params': [{'name': 'action', 'type': 'select', 'label': 'Action', 'options': ['get', 'set', 'delete', 'exists', 'flush', 'stats', 'keys'], 'default': 'get'}, {'name': 'max_size', 'type': 'number', 'label': 'Max Size', 'default': 10000}, {'name': 'default_ttl', 'type': 'number', 'label': 'Default Ttl', 'default': 3600}, {'name': 'cleanup_interval', 'type': 'number', 'label': 'Cleanup Interval', 'default': 300}],
        'quick_actions': [],
    }

    def __init__(self, hal_block, config: Dict[str, Any], namespace: str = "global"):
        super().__init__(hal_block, config)
        self.namespace = namespace
        self.cache = {}  # internal_key -> {value, expiry, access_count}
        self.access_order = OrderedDict()  # LRU tracking
        self.max_size = config.get("max_size", 10000)  # Max items
        self.default_ttl = config.get("default_ttl", 3600)  # 1 hour default
        # Per-namespace statistics for namespace-aware reporting.
        self._namespace_stats = defaultdict(lambda: {"hits": 0, "misses": 0, "evictions": 0})
        # Legacy global stats accumulator kept for backward compatibility.
        self.stats = {"hits": 0, "misses": 0, "evictions": 0}
        self.cleanup_task = None

    @staticmethod
    def _internal_key(namespace: str, key: str) -> str:
        return f"{namespace}{_NS_SEP}{key}"

    def _split_internal_key(self, internal_key: str) -> tuple:
        namespace, _, key = internal_key.partition(_NS_SEP)
        return namespace, key

    def _namespace_key_iter(self, namespace: str):
        """Yield (internal_key, user_key) pairs for the given namespace."""
        prefix = f"{namespace}{_NS_SEP}"
        for internal_key in list(self.cache.keys()):
            if internal_key.startswith(prefix):
                yield internal_key, internal_key[len(prefix):]

    async def _legacy_initialize(self):
        """Start background cleanup"""
        self.cleanup_task = asyncio.create_task(self._cleanup_expired())
        print(f"🧠 Memory Block ready (namespace: {self.namespace}, max: {self.max_size}, TTL: {self.default_ttl}s)")
        return True

    async def process(self, input_data: Dict = None, params: Dict = None) -> Dict:
        """Cache operations: get, set, delete, flush"""
        input_data = input_data if isinstance(input_data, dict) else {}
        params = params if isinstance(params, dict) else {}
        # A caller (e.g. MemoryNamespaceProxy) may request a different namespace.
        namespace = input_data.get("_namespace") or params.get("_namespace") or self.namespace
        action = params.get("action") or input_data.get("action")

        if action == "get":
            return await self._get(namespace, input_data.get("key"))
        elif action == "set":
            return await self._set(
                namespace,
                input_data.get("key"),
                input_data.get("value"),
                input_data.get("ttl", self.default_ttl)
            )
        elif action == "delete":
            return await self._delete(namespace, input_data.get("key"))
        elif action == "exists":
            return {"exists": self._internal_key(namespace, input_data.get("key")) in self.cache}
        elif action == "flush":
            return await self._flush(namespace)
        elif action == "stats":
            return self._get_stats(namespace)
        elif action == "keys":
            return {"keys": [user_key for _, user_key in self._namespace_key_iter(namespace)]}

        return {"error": f"Unknown action: {action}"}

    async def _get(self, namespace: str, key: str) -> Dict:
        """Get value with LRU update"""
        internal_key = self._internal_key(namespace, key)
        ns_stats = self._namespace_stats[namespace]

        if internal_key in self.cache:
            item = self.cache[internal_key]

            # Check TTL
            if time.time() > item["expiry"]:
                del self.cache[internal_key]
                if internal_key in self.access_order:
                    del self.access_order[internal_key]
                ns_stats["misses"] += 1
                self.stats["misses"] += 1
                return {"value": None, "hit": False, "reason": "expired"}

            # Update access order (LRU)
            if internal_key in self.access_order:
                del self.access_order[internal_key]
            self.access_order[internal_key] = None

            ns_stats["hits"] += 1
            self.stats["hits"] += 1
            item["access_count"] += 1

            return {"value": item["value"], "hit": True, "ttl_remaining": item["expiry"] - time.time()}

        ns_stats["misses"] += 1
        self.stats["misses"] += 1
        return {"value": None, "hit": False}

    async def _set(self, namespace: str, key: str, value: Any, ttl: int) -> Dict:
        """Set value with TTL"""
        internal_key = self._internal_key(namespace, key)

        # Eviction if at capacity
        if len(self.cache) >= self.max_size and internal_key not in self.cache:
            await self._evict_lru(namespace)

        expiry = time.time() + ttl if ttl > 0 else float('inf')

        self.cache[internal_key] = {
            "value": value,
            "expiry": expiry,
            "created": time.time(),
            "access_count": 0
        }

        # Update access order
        if internal_key in self.access_order:
            del self.access_order[internal_key]
        self.access_order[internal_key] = None

        return {"stored": True, "key": key, "ttl": ttl}

    async def _delete(self, namespace: str, key: str) -> Dict:
        """Delete key"""
        internal_key = self._internal_key(namespace, key)
        if internal_key in self.cache:
            del self.cache[internal_key]
            if internal_key in self.access_order:
                del self.access_order[internal_key]
            return {"deleted": True}
        return {"deleted": False, "reason": "not_found"}

    async def _flush(self, namespace: str) -> Dict:
        """Clear only keys in the requested namespace"""
        count = 0
        for internal_key, _ in list(self._namespace_key_iter(namespace)):
            del self.cache[internal_key]
            if internal_key in self.access_order:
                del self.access_order[internal_key]
            count += 1
        return {"flushed": True, "count": count}

    async def _evict_lru(self, namespace: str):
        """Evict least recently used item"""
        if not self.access_order:
            return

        # Get oldest item
        oldest_key = next(iter(self.access_order))
        del self.cache[oldest_key]
        del self.access_order[oldest_key]
        self._namespace_stats[namespace]["evictions"] += 1
        self.stats["evictions"] += 1

    async def _cleanup_expired(self):
        """Background task: remove expired keys every 60s"""
        while True:
            await asyncio.sleep(60)
            current_time = time.time()
            expired = [k for k, v in self.cache.items() if current_time > v["expiry"]]
            for k in expired:
                del self.cache[k]
                if k in self.access_order:
                    del self.access_order[k]

    def _get_stats(self, namespace: Optional[str] = None) -> Dict:
        """Get cache statistics for a namespace"""
        namespace = namespace or self.namespace
        ns_stats = self._namespace_stats[namespace]
        total = ns_stats["hits"] + ns_stats["misses"]
        hit_rate = (ns_stats["hits"] / total * 100) if total > 0 else 0
        size = sum(1 for _ in self._namespace_key_iter(namespace))

        return {
            "size": size,
            "max_size": self.max_size,
            "hit_rate_percent": round(hit_rate, 2),
            "hits": ns_stats["hits"],
            "misses": ns_stats["misses"],
            "evictions": ns_stats["evictions"],
            "memory_items": size
        }

    def health(self) -> Dict:
        h = {"name": self.name, "version": self.version}
        h.update(self._get_stats())
        h["utilization_percent"] = round(len(self.cache) / self.max_size * 100, 2)
        return h


class MemoryNamespaceProxy:
    """
    Lightweight namespace view over a backing MemoryBlock.

    Exposes the same ``process()`` API and delegates everything else to the
    backing block. Multiple proxies can share one MemoryBlock while each only
    sees its own namespace.
    """

    def __init__(self, backing_block: MemoryBlock, namespace: str):
        self._backing = backing_block
        self._namespace = namespace

    async def process(self, input_data: Dict = None, params: Dict = None) -> Dict:
        """Forward to the backing block locked to this proxy's namespace."""
        if input_data is None:
            input_data = {}
        elif not isinstance(input_data, dict):
            input_data = {"input": input_data}
        else:
            input_data = dict(input_data)  # do not mutate caller's payload
        input_data["_namespace"] = self._namespace
        return await self._backing.process(input_data, params)

    def __getattr__(self, name: str):
        # Delegate health(), name, version, and other block attributes to the
        # backing instance. Access to the proxy's own attributes never reaches
        # this fallback because they are set in __init__.
        return getattr(self._backing, name)
