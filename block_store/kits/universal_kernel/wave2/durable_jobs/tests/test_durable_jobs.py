"""Tests for the neutral durable jobs sub-kit."""

import pytest

from block_store.kits.universal_kernel.wave2.durable_jobs import (
    JobStateError,
    MemoryJobStore,
    MissingHandlerError,
    PostgresJobStore,
    Worker,
)


def test_enqueue_and_claim():
    store = MemoryJobStore()
    job = store.enqueue("summarize", {"text": "hello"}, priority=1)
    assert job.status == "pending"
    claimed = store.claim_next("worker-a")
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.worker_id == "worker-a"


def test_complete_job():
    store = MemoryJobStore()
    job = store.enqueue("summarize", {"text": "hello"})
    store.claim_next("worker-a")
    completed = store.complete(job.id, {"summary": "hi"})
    assert completed.status == "completed"
    assert completed.result == {"summary": "hi"}


def test_fail_job():
    store = MemoryJobStore()
    job = store.enqueue("summarize", {"text": "hello"})
    store.claim_next("worker-a")
    failed = store.fail(job.id, "boom")
    assert failed.status == "failed"
    assert "boom" in failed.error


def test_cancel_pending_job():
    store = MemoryJobStore()
    job = store.enqueue("summarize", {"text": "hello"})
    cancelled = store.cancel(job.id)
    assert cancelled.status == "cancelled"


def test_idempotency_returns_existing_job():
    store = MemoryJobStore()
    job1 = store.enqueue("summarize", {"text": "hello"}, idempotency_key="key-1")
    job2 = store.enqueue("summarize", {"text": "different"}, idempotency_key="key-1")
    assert job1.id == job2.id


def test_worker_runs_handler():
    store = MemoryJobStore()
    calls = []

    def handler(job):
        calls.append(job.payload)
        return "done"

    worker = Worker(store, {"echo": handler})
    store.enqueue("echo", {"value": 42})
    result_job = worker.run_once()
    assert result_job is not None
    assert result_job.status == "completed"
    assert result_job.result == "done"
    assert calls == [{"value": 42}]


def test_worker_fails_when_handler_missing():
    store = MemoryJobStore()
    worker = Worker(store, {})
    job = store.enqueue("unknown", {"value": 1})
    result_job = worker.run_once()
    assert result_job is not None
    assert result_job.status == "failed"
    assert "no handler" in result_job.error


def test_postgres_store_requires_database_url():
    import os

    old = os.environ.pop("DATABASE_URL", None)
    try:
        with pytest.raises(RuntimeError):
            PostgresJobStore()
    finally:
        if old:
            os.environ["DATABASE_URL"] = old


def test_priority_ordering():
    store = MemoryJobStore()
    low = store.enqueue("task", {"n": 1}, priority=0)
    high = store.enqueue("task", {"n": 2}, priority=10)
    claimed = store.claim_next("worker-a")
    assert claimed.id == high.id
