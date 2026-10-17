"""Neutral durable job queue: in-memory backend and optional PostgreSQL backend."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


class JobStateError(Exception):
    """Raised when a job cannot transition to the requested state."""


class MissingHandlerError(Exception):
    """Raised when no handler exists for a job model."""


@dataclass
class Job:
    """Neutral durable job record."""

    id: str
    model: str
    payload: Dict[str, Any]
    priority: int = 0
    status: str = "pending"
    result: Any = None
    error: Optional[str] = None
    worker_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class JobStore(ABC):
    """Abstract job store interface."""

    @abstractmethod
    def enqueue(
        self,
        model: str,
        payload: Dict[str, Any],
        priority: int = 0,
        idempotency_key: Optional[str] = None,
    ) -> Job:
        raise NotImplementedError

    @abstractmethod
    def claim_next(self, worker_id: str) -> Optional[Job]:
        raise NotImplementedError

    @abstractmethod
    def complete(self, job_id: str, result: Any) -> Job:
        raise NotImplementedError

    @abstractmethod
    def fail(self, job_id: str, error: str) -> Job:
        raise NotImplementedError

    @abstractmethod
    def cancel(self, job_id: str) -> Job:
        raise NotImplementedError

    @abstractmethod
    def get(self, job_id: str) -> Optional[Job]:
        raise NotImplementedError


class MemoryJobStore(JobStore):
    """In-memory job store with idempotency and status transitions."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._idempotency: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._counter = 0

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _generate_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"job-{self._counter:08d}"

    def enqueue(
        self,
        model: str,
        payload: Dict[str, Any],
        priority: int = 0,
        idempotency_key: Optional[str] = None,
    ) -> Job:
        with self._lock:
            if idempotency_key:
                existing_id = self._idempotency.get(idempotency_key)
                if existing_id and existing_id in self._jobs:
                    return self._jobs[existing_id]

            job_id = self._generate_id()
            job = Job(
                id=job_id,
                model=model,
                payload=payload,
                priority=priority,
                idempotency_key=idempotency_key,
                status="pending",
                created_at=self._now(),
                updated_at=self._now(),
            )
            self._jobs[job_id] = job
            if idempotency_key:
                self._idempotency[idempotency_key] = job_id
            return job

    def claim_next(self, worker_id: str) -> Optional[Job]:
        with self._lock:
            candidates = [
                job for job in self._jobs.values()
                if job.status == "pending"
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda j: (-j.priority, j.created_at))
            job = candidates[0]
            job.status = "running"
            job.worker_id = worker_id
            job.updated_at = self._now()
            return job

    def complete(self, job_id: str, result: Any) -> Job:
        with self._lock:
            job = self._get_locked(job_id)
            if job.status != "running":
                raise JobStateError(f"job {job_id} is not running")
            job.status = "completed"
            job.result = result
            job.updated_at = self._now()
            return job

    def fail(self, job_id: str, error: str) -> Job:
        with self._lock:
            job = self._get_locked(job_id)
            if job.status not in {"running", "pending"}:
                raise JobStateError(f"job {job_id} cannot be failed from {job.status}")
            job.status = "failed"
            job.error = str(error)
            job.updated_at = self._now()
            return job

    def cancel(self, job_id: str) -> Job:
        with self._lock:
            job = self._get_locked(job_id)
            if job.status in {"completed", "failed"}:
                raise JobStateError(f"job {job_id} is already terminal")
            job.status = "cancelled"
            job.updated_at = self._now()
            return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def _get_locked(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobStateError(f"job {job_id} not found")
        return job


class PostgresJobStore(JobStore):
    """Optional PostgreSQL job store stub; requires DATABASE_URL to initialize."""

    def __init__(self, connection_string: Optional[str] = None) -> None:
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        if not self.connection_string:
            raise RuntimeError("DATABASE_URL is required for PostgresJobStore")
        # Backend stub: no actual table operations in this neutral kit.
        self._jobs: Dict[str, Job] = {}
        self._idempotency: Dict[str, str] = {}

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def enqueue(
        self,
        model: str,
        payload: Dict[str, Any],
        priority: int = 0,
        idempotency_key: Optional[str] = None,
    ) -> Job:
        if idempotency_key and idempotency_key in self._idempotency:
            existing_id = self._idempotency[idempotency_key]
            return self._jobs[existing_id]
        job_id = hashlib.sha256(
            f"{model}:{json.dumps(payload, sort_keys=True)}:{time.time()}".encode()
        ).hexdigest()[:16]
        job = Job(
            id=job_id,
            model=model,
            payload=payload,
            priority=priority,
            idempotency_key=idempotency_key,
            status="pending",
            created_at=self._now(),
            updated_at=self._now(),
        )
        self._jobs[job_id] = job
        if idempotency_key:
            self._idempotency[idempotency_key] = job_id
        return job

    def claim_next(self, worker_id: str) -> Optional[Job]:
        candidates = [job for job in self._jobs.values() if job.status == "pending"]
        if not candidates:
            return None
        candidates.sort(key=lambda j: (-j.priority, j.created_at))
        job = candidates[0]
        job.status = "running"
        job.worker_id = worker_id
        job.updated_at = self._now()
        return job

    def complete(self, job_id: str, result: Any) -> Job:
        job = self._get(job_id)
        if job.status != "running":
            raise JobStateError(f"job {job_id} is not running")
        job.status = "completed"
        job.result = result
        job.updated_at = self._now()
        return job

    def fail(self, job_id: str, error: str) -> Job:
        job = self._get(job_id)
        if job.status not in {"running", "pending"}:
            raise JobStateError(f"job {job_id} cannot be failed from {job.status}")
        job.status = "failed"
        job.error = str(error)
        job.updated_at = self._now()
        return job

    def cancel(self, job_id: str) -> Job:
        job = self._get(job_id)
        if job.status in {"completed", "failed"}:
            raise JobStateError(f"job {job_id} is already terminal")
        job.status = "cancelled"
        job.updated_at = self._now()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def _get(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobStateError(f"job {job_id} not found")
        return job


class Worker:
    """Polling worker that executes jobs from a store using registered handlers."""

    def __init__(
        self,
        store: JobStore,
        handlers: Dict[str, Callable[[Job], Any]],
    ) -> None:
        self.store = store
        self.handlers = dict(handlers)
        self._stop = threading.Event()

    def run_once(self) -> Optional[Job]:
        job = self.store.claim_next("worker-1")
        if job is None:
            return None
        handler = self.handlers.get(job.model)
        if handler is None:
            self.store.fail(job.id, f"no handler registered for model {job.model!r}")
            return self.store.get(job.id)
        try:
            result = handler(job)
            return self.store.complete(job.id, result)
        except Exception as exc:  # noqa: BLE001
            return self.store.fail(job.id, str(exc))

    def run_forever(self, interval: float = 1.0) -> None:
        self._stop.clear()
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(interval)

    def stop(self) -> None:
        self._stop.set()
