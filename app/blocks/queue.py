"""Queue Block - job queue with two backends behind one interface.

REDIS_URL set   -> Redis (redis-py, connection-pooled). Jobs survive a
                   restart. A reserved (dequeued) job that is not acked
                   reappears at the head of its queue once the visibility
                   timeout elapses.
REDIS_URL unset -> the in-process deque this block has always had. Jobs are
                   lost on restart, and every result says so.

The backend is chosen once, on first use, and every result names it:
``backend`` is ``"memory"`` or ``"redis"``; ``persistence`` is
``"in_process"`` or ``"redis"``. If REDIS_URL is set but Redis cannot be
reached the block falls back to memory and declares ``redis:
"configured_but_unreachable"`` rather than pretending.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from collections import deque
from enum import Enum
from typing import Any, Callable, Dict, Optional

from app.core.universal_base import UniversalBlock

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


_DEFAULT_VISIBILITY_TIMEOUT = 30.0


class QueueBlock(UniversalBlock):
    """
    Job queue. Redis backend when REDIS_URL is set (durable, visibility
    timeout on reserve); in-process deque otherwise (lost on restart).
    """

    name = "queue"
    version = "1.1.0"
    requires = ["config", "memory"]
    layer = 2  # Core layer
    tags = ["queue", "jobs", "async", "core"]
    default_config = {
        "backend": "auto",
        "redis_url": None,
        "max_workers": 4,
        "visibility_timeout": _DEFAULT_VISIBILITY_TIMEOUT,
        "key_prefix": "cerebrum:queue",
    }

    ui_schema = {
        'input': {'type': 'json', 'accept': None, 'placeholder': 'Job type, payload, queue name', 'multiline': True},
        'output': {'type': 'json', 'fields': [{'name': 'result', 'type': 'json', 'label': 'Result'}]},
        'params': [
            {'name': 'action', 'type': 'select', 'label': 'Action', 'options': ['enqueue', 'dequeue', 'ack', 'status', 'list'], 'default': 'enqueue'},
            {'name': 'backend', 'type': 'text', 'label': 'Backend (auto: redis when REDIS_URL is set, else memory)', 'default': 'auto'},
            {'name': 'redis_url', 'type': 'text', 'label': 'Redis Url (REDIS_URL env takes precedence)', 'default': None},
            {'name': 'visibility_timeout', 'type': 'number', 'label': 'Visibility timeout (s, redis backend)', 'default': _DEFAULT_VISIBILITY_TIMEOUT},
            {'name': 'max_workers', 'type': 'number', 'label': 'Max Workers', 'default': 4},
        ],
        'quick_actions': [],
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block, config)
        self.memory_block = None
        cfg = config or {}
        # Env is the contract; the config key is a lower-precedence seam.
        self.redis_url = os.getenv("REDIS_URL", "").strip() or cfg.get("redis_url") or None
        self._redis_from_env = bool(os.getenv("REDIS_URL", "").strip())
        self.visibility_timeout = float(
            os.getenv("QUEUE_VISIBILITY_TIMEOUT", "") or cfg.get("visibility_timeout") or _DEFAULT_VISIBILITY_TIMEOUT
        )
        self.key_prefix = cfg.get("key_prefix") or "cerebrum:queue"

        # Resolved lazily on first process() call (needs an event loop).
        self._backend: Optional[str] = None          # "memory" | "redis"
        self._redis = None                           # redis.asyncio.Redis when backend == "redis"
        self._redis_state = "not_configured" if not self.redis_url else "unresolved"
        self._backend_lock = asyncio.Lock()

        # In-memory queue
        self._queues = {}  # queue_name -> deque
        self._jobs = {}    # job_id -> job_data (memory backend; on redis: jobs this process has seen)
        self._handlers = {}  # job_type -> handler_func
        self._running = False
        self._worker_task = None

    # ── backend resolution ──────────────────────────────────────────────

    @property
    def use_redis(self) -> bool:
        return self._backend == "redis"

    async def _resolve_backend(self) -> str:
        if self._backend is not None:
            return self._backend
        async with self._backend_lock:
            if self._backend is not None:
                return self._backend
            client = None
            if self.redis_url:
                client = await self._connect_redis()
            if client is None:
                self._backend = "memory"
                if self.redis_url:
                    self._redis_state = "configured_but_unreachable"
            else:
                self._redis = client
                self._backend = "redis"
                self._redis_state = "connected"
            return self._backend

    async def _connect_redis(self):
        """Pooled async client: the platform-shared one for REDIS_URL, a
        block-owned one for a config-supplied URL. None if unreachable."""
        if self._redis_from_env:
            from app.core import redis_infra
            return await redis_infra.get_redis_client()
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(self.redis_url, decode_responses=True)
            await client.ping()
            return client
        except Exception as exc:
            logger.warning("queue: config redis_url unreachable (%s); falling back to memory", exc)
            return None

    def _backend_fields(self) -> Dict[str, Any]:
        fields = {
            "backend": self._backend or "unresolved",
            "persistence": "redis" if self._backend == "redis" else "in_process",
        }
        if self._backend == "redis":
            fields["visibility_timeout"] = self.visibility_timeout
        elif self.redis_url:
            fields["redis"] = self._redis_state
        return fields

    # ── redis key layout ────────────────────────────────────────────────

    def _qkey(self, queue: str) -> str:
        return f"{self.key_prefix}:q:{queue}"

    def _rkey(self, queue: str) -> str:
        return f"{self.key_prefix}:reserved:{queue}"

    def _jkey(self, job_id: str) -> str:
        return f"{self.key_prefix}:job:{job_id}"

    def _qset(self) -> str:
        return f"{self.key_prefix}:queues"

    async def _save_job(self, job: Dict) -> None:
        if self._backend == "redis":
            await self._redis.set(self._jkey(job["id"]), json.dumps(job, default=str))
        # memory: the dict in self._jobs is the record; nothing to do.

    async def _load_job(self, job_id: str) -> Optional[Dict]:
        if self._backend == "redis":
            raw = await self._redis.get(self._jkey(job_id))
            return json.loads(raw) if raw else None
        return self._jobs.get(job_id)

    # ── lifecycle ───────────────────────────────────────────────────────

    async def _legacy_initialize(self):
        """Initialize queue"""
        backend = await self._resolve_backend()
        print("📬 Queue Block initialized")
        if backend == "redis":
            print(f"   Backend: redis (visibility timeout {self.visibility_timeout}s)")
        else:
            print(f"   Backend: in-process memory (redis: {self._redis_state})")

        # Start worker
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())

        return True

    def register_handler(self, job_type: str, handler: Callable):
        """Register a job handler"""
        self._handlers[job_type] = handler
        print(f"   Handler registered: {job_type}")

    # ── public interface ────────────────────────────────────────────────

    async def process(self, input_data: Dict, params: Dict = None) -> Dict:
        """Queue operations"""
        input_data = input_data or {}
        action = (params or {}).get("action") or input_data.get("action")
        await self._resolve_backend()

        if action == "enqueue":
            return await self._enqueue(input_data)
        elif action == "dequeue":
            return await self._dequeue(input_data.get("queue", "default"))
        elif action == "ack":
            return await self._ack(input_data.get("job_id"))
        elif action == "status":
            return await self._get_status(input_data.get("job_id") if input_data else None)
        elif action == "list":
            return await self._list_jobs(input_data.get("queue", "default"))

        return {"error": f"Unknown action: {action}"}

    async def _enqueue(self, data: Dict) -> Dict:
        """Add job to queue"""
        await self._resolve_backend()
        job_id = f"job_{int(time.time() * 1000)}"
        if self._backend == "redis":
            job_id = f"{job_id}_{uuid.uuid4().hex[:8]}"
        job = {
            "id": job_id,
            "type": data.get("job_type"),
            "payload": data.get("payload", {}),
            "queue": data.get("queue", "default"),
            "priority": data.get("priority", 0),  # 0 = normal, 1 = high
            "status": JobStatus.PENDING.value,
            "created_at": time.time(),
            "retry_count": 0,
            "max_retries": data.get("max_retries", 3),
        }
        queue_name = job["queue"]

        if self._backend == "redis":
            r = self._redis
            await self._save_job(job)
            if job["priority"] > 0:
                await r.lpush(self._qkey(queue_name), job_id)
            else:
                await r.rpush(self._qkey(queue_name), job_id)
            await r.sadd(self._qset(), queue_name)
        else:
            if queue_name not in self._queues:
                self._queues[queue_name] = deque()
            if job["priority"] > 0:
                self._queues[queue_name].appendleft(job)
            else:
                self._queues[queue_name].append(job)
        self._jobs[job["id"]] = job

        return {"enqueued": True, "job_id": job["id"], **self._backend_fields()}

    async def _reclaim_expired(self, queue_name: str) -> int:
        """Redis: move every reservation past its deadline back to the head
        of the queue. Returns how many were re-delivered."""
        r = self._redis
        now = time.time()
        expired = await r.zrangebyscore(self._rkey(queue_name), "-inf", now)
        reclaimed = 0
        for job_id in expired:
            # ZREM is the claim: only the caller that removes it re-queues it.
            if not await r.zrem(self._rkey(queue_name), job_id):
                continue
            job = await self._load_job(job_id)
            if job is not None:
                job["status"] = JobStatus.PENDING.value
                job["redelivered"] = int(job.get("redelivered", 0)) + 1
                job.pop("reserved_until", None)
                await self._save_job(job)
            await r.lpush(self._qkey(queue_name), job_id)
            reclaimed += 1
        return reclaimed

    async def _dequeue(self, queue_name: str) -> Optional[Dict]:
        """Get next job from queue"""
        await self._resolve_backend()
        if self._backend == "redis":
            r = self._redis
            await self._reclaim_expired(queue_name)
            job_id = await r.lpop(self._qkey(queue_name))
            if job_id is None:
                return None
            job = await self._load_job(job_id)
            if job is None:
                return None  # dangling id (record expired or deleted)
            now = time.time()
            job["status"] = JobStatus.RUNNING.value
            job["started_at"] = now
            job["reserved_until"] = now + self.visibility_timeout
            await r.zadd(self._rkey(queue_name), {job_id: job["reserved_until"]})
            await self._save_job(job)
            self._jobs[job_id] = job
            return job

        if queue_name in self._queues and self._queues[queue_name]:
            job = self._queues[queue_name].popleft()
            job["status"] = JobStatus.RUNNING.value
            job["started_at"] = time.time()
            return job

        return None

    async def _ack(self, job_id: Optional[str]) -> Dict:
        """Acknowledge a dequeued job: it is done and must not be re-delivered."""
        await self._resolve_backend()
        if not job_id:
            return {"error": "job_id required", "acked": False}
        job = await self._load_job(job_id)
        if job is None:
            return {"error": "job_not_found", "job_id": job_id, "acked": False}

        if self._backend == "redis":
            removed = await self._redis.zrem(self._rkey(job["queue"]), job_id)
            if not removed:
                return {
                    "acked": False,
                    "job_id": job_id,
                    "reason": "not_reserved (never dequeued, already acked, or visibility timeout expired and re-delivered)",
                    **self._backend_fields(),
                }
        job["status"] = JobStatus.COMPLETED.value
        job["completed_at"] = time.time()
        job.pop("reserved_until", None)
        await self._save_job(job)
        self._jobs[job_id] = job
        return {"acked": True, "job_id": job_id, **self._backend_fields()}

    async def _release(self, job: Dict) -> None:
        """Worker-internal: drop the reservation without changing status."""
        if self._backend == "redis":
            await self._redis.zrem(self._rkey(job["queue"]), job["id"])

    async def _get_status(self, job_id: str) -> Dict:
        """Get job status"""
        await self._resolve_backend()
        job = await self._load_job(job_id) if job_id else None
        if job is not None:
            return {
                "job_id": job_id,
                "status": job["status"],
                "type": job["type"],
                "created_at": job["created_at"],
            }
        return {"error": "job_not_found"}

    async def _list_jobs(self, queue_name: str) -> Dict:
        """List jobs in queue"""
        await self._resolve_backend()
        if self._backend == "redis":
            r = self._redis
            await self._reclaim_expired(queue_name)
            ids = await r.lrange(self._qkey(queue_name), 0, 9)
            jobs = []
            for job_id in ids:
                job = await self._load_job(job_id)
                if job is not None:
                    jobs.append({"id": job["id"], "type": job["type"]})
            return {
                "queue": queue_name,
                "pending": await r.llen(self._qkey(queue_name)),
                "reserved": await r.zcard(self._rkey(queue_name)),
                "jobs": jobs,
            }
        if queue_name in self._queues:
            jobs = list(self._queues[queue_name])
            return {
                "queue": queue_name,
                "pending": len(jobs),
                "jobs": [{"id": j["id"], "type": j["type"]} for j in jobs[:10]]
            }
        return {"queue": queue_name, "pending": 0, "jobs": []}

    async def _known_queues(self):
        if self._backend == "redis":
            return list(await self._redis.smembers(self._qset()))
        return list(self._queues.keys())

    async def _worker(self):
        """Background worker"""
        while self._running:
            try:
                # Try each queue
                for queue_name in await self._known_queues():
                    job = await self._dequeue(queue_name)
                    if job:
                        await self._process_job(job)
                        await self._release(job)

                await asyncio.sleep(0.1)  # Small delay
            except Exception as e:
                print(f"Worker error: {e}")
                await asyncio.sleep(1)

    async def _process_job(self, job: Dict):
        """Process a job"""
        handler = self._handlers.get(job["type"])
        if not handler:
            job["status"] = JobStatus.FAILED.value
            job["error"] = "no_handler"
            await self._save_job(job)
            return

        try:
            result = await handler(job["payload"])
            job["status"] = JobStatus.COMPLETED.value
            job["result"] = result
            job["completed_at"] = time.time()
        except Exception as e:
            job["retry_count"] += 1
            if job["retry_count"] >= job["max_retries"]:
                job["status"] = JobStatus.FAILED.value
                job["error"] = str(e)
            else:
                job["status"] = JobStatus.RETRYING.value
                # Re-queue
                await self._enqueue({
                    "job_type": job["type"],
                    "payload": job["payload"],
                    "queue": job["queue"],
                })
        await self._save_job(job)

    def health(self) -> Dict[str, Any]:
        """Health check"""
        h = {"name": self.name, "version": self.version}
        h.update(self._backend_fields())
        h["redis_implemented"] = True
        h["redis_configured"] = bool(self.redis_url)
        h["redis_state"] = self._redis_state
        h["queues"] = list(self._queues.keys()) if self._backend != "redis" else "see list action"
        h["handlers"] = list(self._handlers.keys())
        h["total_jobs"] = len(self._jobs)
        return h
