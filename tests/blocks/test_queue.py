"""Queue block: one interface, two backends, chosen by REDIS_URL.

Fixture: a fakeredis server (an in-process Redis implementation with the real
data-structure semantics) stands in for REDIS_URL. ``redis.asyncio.from_url``
is the only thing replaced, and it is replaced at the shared
``app.core.redis_infra`` seam the block consumes, so the block's own key
layout, LPOP/LPUSH ordering, ZSET reservations and JSON job records run for
real against a server that keeps state between block instances.

Every assertion is on a value ``QueueBlock.process`` computed: the job id it
minted, the backend it declared, the payload it handed back on dequeue, the
re-delivery it performed after the visibility timeout, and the refusal to
ack a reservation that had already expired.
"""

from __future__ import annotations

import asyncio
import copy

import fakeredis
import fakeredis.aioredis
import pytest

from app.blocks.queue import QueueBlock
from app.core import redis_infra

PAYLOAD = {"document": "spec-rev-B.pdf", "pages": [1, 2, 3], "priority_note": "urgent"}


@pytest.fixture
def memory_env(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("QUEUE_VISIBILITY_TIMEOUT", raising=False)
    redis_infra.reset_for_tests()
    yield
    redis_infra.reset_for_tests()


@pytest.fixture
def redis_env(monkeypatch):
    """REDIS_URL set; the URL is never dialled -- from_url returns a client
    bound to one fakeredis server shared by every block in the test."""
    server = fakeredis.FakeServer()

    def fake_from_url(url, **kwargs):
        assert url == "redis://queue-under-test:6379/0"
        return fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)

    monkeypatch.setenv("REDIS_URL", "redis://queue-under-test:6379/0")
    monkeypatch.delenv("QUEUE_VISIBILITY_TIMEOUT", raising=False)
    redis_infra.reset_for_tests()
    monkeypatch.setattr(redis_infra.aioredis, "from_url", fake_from_url)
    yield server
    redis_infra.reset_for_tests()


async def _run(block: QueueBlock, action: str, **data):
    return await block.process(data, {"action": action})


# ── memory backend (no REDIS_URL): unchanged behaviour, declared ──────────


async def test_memory_backend_roundtrip_and_declares_itself(memory_env):
    block = QueueBlock(None, {})
    queued = await _run(block, "enqueue", job_type="ocr", payload=PAYLOAD)
    assert queued["enqueued"] is True
    assert queued["job_id"].startswith("job_")
    assert queued["backend"] == "memory"
    assert queued["persistence"] == "in_process"
    assert "redis" not in queued, "no Redis claim of any kind without REDIS_URL"

    listed = await _run(block, "list", queue="default")
    assert listed["pending"] == 1
    assert listed["jobs"] == [{"id": queued["job_id"], "type": "ocr"}]

    job = await _run(block, "dequeue", queue="default")
    assert job["id"] == queued["job_id"]
    assert job["payload"] == PAYLOAD
    assert job["status"] == "running"
    assert (await _run(block, "status", job_id=job["id"]))["status"] == "running"

    acked = await _run(block, "ack", job_id=job["id"])
    assert acked == {"acked": True, "job_id": job["id"], "backend": "memory", "persistence": "in_process"}
    assert (await _run(block, "status", job_id=job["id"]))["status"] == "completed"
    assert await _run(block, "dequeue", queue="default") is None

    health = block.health()
    assert health["backend"] == "memory"
    assert health["redis_configured"] is False
    assert health["redis_state"] == "not_configured"


async def test_memory_backend_priority_goes_to_head(memory_env):
    block = QueueBlock(None, {})
    a = await _run(block, "enqueue", job_type="a", payload={})
    b = await _run(block, "enqueue", job_type="b", payload={})
    hi = await _run(block, "enqueue", job_type="hi", priority=1, payload={})
    order = [(await _run(block, "dequeue", queue="default"))["id"] for _ in range(3)]
    assert order == [hi["job_id"], a["job_id"], b["job_id"]]


# ── redis backend ──────────────────────────────────────────────────────────


async def test_redis_backend_roundtrip_on_fakeredis(redis_env):
    block = QueueBlock(None, {})
    queued = await _run(block, "enqueue", job_type="ocr", payload=PAYLOAD, queue="docs")
    assert queued["enqueued"] is True
    assert queued["backend"] == "redis"
    assert queued["persistence"] == "redis"
    assert queued["visibility_timeout"] == 30.0
    assert block.use_redis is True

    # The record is in Redis, not just in this process.
    client = fakeredis.aioredis.FakeRedis(server=redis_env, decode_responses=True)
    assert await client.llen("cerebrum:queue:q:docs") == 1
    assert await client.exists(f"cerebrum:queue:job:{queued['job_id']}") == 1

    listed = await _run(block, "list", queue="docs")
    assert listed == {"queue": "docs", "pending": 1, "reserved": 0, "jobs": [{"id": queued["job_id"], "type": "ocr"}]}

    job = await _run(block, "dequeue", queue="docs")
    assert job["id"] == queued["job_id"]
    assert job["payload"] == PAYLOAD
    assert job["status"] == "running"
    assert job["reserved_until"] > job["started_at"]
    assert (await _run(block, "list", queue="docs"))["reserved"] == 1
    assert (await _run(block, "status", job_id=job["id"]))["status"] == "running"

    acked = await _run(block, "ack", job_id=job["id"])
    assert acked["acked"] is True and acked["backend"] == "redis"
    assert (await _run(block, "list", queue="docs"))["reserved"] == 0
    assert (await _run(block, "status", job_id=job["id"]))["status"] == "completed"
    assert await _run(block, "dequeue", queue="docs") is None


async def test_redis_backend_survives_a_new_block_instance(redis_env):
    producer = QueueBlock(None, {})
    queued = await _run(producer, "enqueue", job_type="ocr", payload=PAYLOAD)

    consumer = QueueBlock(None, {})  # empty in-process state
    assert consumer._jobs == {} and consumer._queues == {}
    job = await _run(consumer, "dequeue", queue="default")
    assert job["id"] == queued["job_id"]
    assert job["payload"] == PAYLOAD
    assert (await _run(consumer, "status", job_id=job["id"]))["status"] == "running"


async def test_redis_visibility_timeout_redelivers_unacked_job(redis_env):
    block = QueueBlock(None, {"visibility_timeout": 0.05})
    queued = await _run(block, "enqueue", job_type="ocr", payload=PAYLOAD)

    first = await _run(block, "dequeue", queue="default")
    assert first["id"] == queued["job_id"]
    assert await _run(block, "dequeue", queue="default") is None, "reserved, not visible"

    await asyncio.sleep(0.12)
    again = await _run(block, "dequeue", queue="default")
    assert again is not None, "unacked reservation must reappear after the visibility timeout"
    assert again["id"] == queued["job_id"]
    assert again["payload"] == PAYLOAD
    assert again["redelivered"] == 1
    assert again["status"] == "running"

    assert (await _run(block, "ack", job_id=again["id"]))["acked"] is True
    await asyncio.sleep(0.12)
    assert await _run(block, "dequeue", queue="default") is None, "an acked job is never re-delivered"


async def test_redis_ack_after_expiry_is_refused_not_faked(redis_env):
    block = QueueBlock(None, {"visibility_timeout": 0.05})
    queued = await _run(block, "enqueue", job_type="ocr", payload=PAYLOAD)
    await _run(block, "dequeue", queue="default")
    await asyncio.sleep(0.12)
    # list reclaims the expired reservation back onto the queue
    listed = await _run(block, "list", queue="default")
    assert listed["pending"] == 1 and listed["reserved"] == 0

    late = await _run(block, "ack", job_id=queued["job_id"])
    assert late["acked"] is False
    assert "visibility timeout" in late["reason"]
    assert (await _run(block, "status", job_id=queued["job_id"]))["status"] == "pending"


async def test_redis_priority_goes_to_head(redis_env):
    block = QueueBlock(None, {})
    a = await _run(block, "enqueue", job_type="a", payload={})
    b = await _run(block, "enqueue", job_type="b", payload={})
    hi = await _run(block, "enqueue", job_type="hi", priority=1, payload={})
    order = [(await _run(block, "dequeue", queue="default"))["id"] for _ in range(3)]
    assert order == [hi["job_id"], a["job_id"], b["job_id"]]


async def test_redis_worker_runs_handler_and_releases_reservation(redis_env):
    block = QueueBlock(None, {})
    seen = []

    async def handler(payload):
        seen.append(payload)
        return {"pages": len(payload["pages"])}

    block.register_handler("ocr", handler)
    assert await block._legacy_initialize() is True
    try:
        queued = await _run(block, "enqueue", job_type="ocr", payload=PAYLOAD)
        for _ in range(50):
            await asyncio.sleep(0.05)
            if (await _run(block, "status", job_id=queued["job_id"]))["status"] == "completed":
                break
        assert seen == [PAYLOAD]
        assert (await _run(block, "status", job_id=queued["job_id"]))["status"] == "completed"
        assert (await _run(block, "list", queue="default"))["reserved"] == 0
    finally:
        block._running = False
        block._worker_task.cancel()
        try:
            await block._worker_task
        except asyncio.CancelledError:
            pass


async def test_redis_configured_but_unreachable_is_declared_not_hidden(redis_env, monkeypatch):
    async def unreachable():
        return None

    monkeypatch.setattr(redis_infra, "get_redis_client", unreachable)
    block = QueueBlock(None, {})
    queued = await _run(block, "enqueue", job_type="ocr", payload=PAYLOAD)
    assert queued["backend"] == "memory"
    assert queued["persistence"] == "in_process"
    assert queued["redis"] == "configured_but_unreachable"
    health = block.health()
    assert health["redis_configured"] is True
    assert health["redis_state"] == "configured_but_unreachable"


# ── the public contract is the same on both backends ───────────────────────

_BACKEND_ONLY = {"backend", "persistence", "visibility_timeout", "redis", "reserved", "redelivered", "reserved_until"}


async def _script(block: QueueBlock):
    out = {}
    out["enqueue"] = await _run(block, "enqueue", job_type="ocr", payload=PAYLOAD, queue="docs")
    out["list"] = await _run(block, "list", queue="docs")
    # snapshot: the memory backend hands back its live record, which ack mutates
    out["dequeue"] = copy.deepcopy(await _run(block, "dequeue", queue="docs"))
    out["status"] = await _run(block, "status", job_id=out["enqueue"]["job_id"])
    out["ack"] = await _run(block, "ack", job_id=out["enqueue"]["job_id"])
    out["status_after_ack"] = await _run(block, "status", job_id=out["enqueue"]["job_id"])
    out["empty"] = await _run(block, "dequeue", queue="docs")
    out["missing"] = await _run(block, "status", job_id="job_nope")
    out["unknown"] = await _run(block, "bogus")
    return out


def _shape(result):
    if isinstance(result, dict):
        return {k: _shape(v) for k, v in result.items() if k not in _BACKEND_ONLY}
    if isinstance(result, list):
        return [_shape(v) for v in result]
    return type(result).__name__


async def test_public_contract_identical_across_backends(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("QUEUE_VISIBILITY_TIMEOUT", raising=False)
    redis_infra.reset_for_tests()
    memory = await _script(QueueBlock(None, {}))

    server = fakeredis.FakeServer()
    monkeypatch.setenv("REDIS_URL", "redis://queue-under-test:6379/0")
    monkeypatch.setattr(
        redis_infra.aioredis,
        "from_url",
        lambda url, **kw: fakeredis.aioredis.FakeRedis(server=server, decode_responses=True),
    )
    redis_infra.reset_for_tests()
    redis = await _script(QueueBlock(None, {}))
    redis_infra.reset_for_tests()

    assert memory["enqueue"]["backend"] == "memory" and redis["enqueue"]["backend"] == "redis"
    assert _shape(memory) == _shape(redis)
    for step in ("dequeue", "status", "status_after_ack", "ack"):
        assert {k: v for k, v in memory[step].items() if k in ("status", "type", "acked")} == {
            k: v for k, v in redis[step].items() if k in ("status", "type", "acked")
        }
    assert memory["dequeue"]["payload"] == redis["dequeue"]["payload"] == PAYLOAD
    assert memory["empty"] is None and redis["empty"] is None
    assert memory["missing"] == redis["missing"] == {"error": "job_not_found"}
    assert memory["unknown"] == redis["unknown"] == {"error": "Unknown action: bogus"}
