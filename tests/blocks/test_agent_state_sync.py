"""Agent state sync tests — vector-clock semantics from <private-repo>."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.agent_state_sync import AgentStateSyncBlock


def _run(coro):
    return asyncio.run(coro)


def test_dominating_clock_applies():
    b = AgentStateSyncBlock()
    r1 = _run(b.process({"action": "apply", "deltas": [{"key": "k", "value": "v1", "origin": "a", "vector_clock": {"a": 1}}]}))
    assert r1["result"]["applied"] == 1
    r2 = _run(b.process({"action": "apply", "deltas": [{"key": "k", "value": "v2", "origin": "a", "vector_clock": {"a": 2}}]}))
    assert r2["result"]["applied"] == 1
    got = _run(b.process({"action": "get", "key": "k"}))
    assert got["result"]["value"]["value"] == "v2"


def test_stale_clock_dropped():
    b = AgentStateSyncBlock()
    _run(b.process({"action": "apply", "deltas": [{"key": "k", "value": "v2", "origin": "a", "vector_clock": {"a": 2}}]}))
    r = _run(b.process({"action": "apply", "deltas": [{"key": "k", "value": "stale", "origin": "a", "vector_clock": {"a": 1}}]}))
    assert r["result"]["applied"] == 0
    assert r["result"]["conflicted"] == 0


def test_incomparable_clocks_archived():
    b = AgentStateSyncBlock()
    _run(b.process({"action": "apply", "deltas": [{"key": "k", "value": "v1", "origin": "a", "vector_clock": {"a": 2, "b": 0}}]}))
    r = _run(b.process({"action": "apply", "deltas": [{"key": "k", "value": "v2", "origin": "b", "vector_clock": {"a": 0, "b": 2}}]}))
    assert r["result"]["conflicted"] == 1
    conflicts = _run(b.process({"action": "conflicts"}))
    assert conflicts["result"]["count"] == 1
    assert conflicts["result"]["conflicts"][0]["key"] == "k"


def test_delta_without_clock_refused():
    b = AgentStateSyncBlock()
    r = _run(b.process({"action": "apply", "deltas": [{"key": "k"}]}))
    assert r["status"] == "error"
