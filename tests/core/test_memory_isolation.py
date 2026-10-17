"""Memory namespace isolation tests for third-party blocks."""

import pytest

from app.blocks.memory import MemoryBlock, MemoryNamespaceProxy


@pytest.mark.asyncio
async def test_block_a_cannot_read_block_b_keys():
    """Keys stored by one namespace must be invisible to another."""
    backing = MemoryBlock(None, {"max_size": 1000, "default_ttl": 3600})

    block_a = MemoryNamespaceProxy(backing, "block:a")
    block_b = MemoryNamespaceProxy(backing, "block:b")

    await block_a.process({"action": "set", "key": "secret", "value": "A"})

    # Same logical key, different namespace -> miss.
    result = await block_b.process({"action": "get", "key": "secret"})
    assert result["hit"] is False
    assert result["value"] is None

    result = await block_b.process({"action": "exists", "key": "secret"})
    assert result["exists"] is False


@pytest.mark.asyncio
async def test_block_a_cannot_flush_block_b_keys():
    """Flushing one namespace must leave other namespaces untouched."""
    backing = MemoryBlock(None, {"max_size": 1000, "default_ttl": 3600})

    block_a = MemoryNamespaceProxy(backing, "block:a")
    block_b = MemoryNamespaceProxy(backing, "block:b")

    await block_a.process({"action": "set", "key": "secret", "value": "A"})
    await block_b.process({"action": "set", "key": "other", "value": "B"})

    flush_result = await block_b.process({"action": "flush"})
    assert flush_result["flushed"] is True
    # Only block_b's key should have been removed.
    assert flush_result["count"] == 1

    result = await block_a.process({"action": "get", "key": "secret"})
    assert result["hit"] is True
    assert result["value"] == "A"

    result = await block_b.process({"action": "get", "key": "other"})
    assert result["hit"] is False


@pytest.mark.asyncio
async def test_keys_only_returns_caller_namespace():
    """keys() must strip the namespace prefix and exclude other namespaces."""
    backing = MemoryBlock(None, {"max_size": 1000, "default_ttl": 3600})

    block_a = MemoryNamespaceProxy(backing, "block:a")
    block_b = MemoryNamespaceProxy(backing, "block:b")

    await block_a.process({"action": "set", "key": "a-key", "value": 1})
    await block_b.process({"action": "set", "key": "b-key", "value": 2})

    a_keys = (await block_a.process({"action": "keys"}))["keys"]
    b_keys = (await block_b.process({"action": "keys"}))["keys"]

    assert a_keys == ["a-key"]
    assert b_keys == ["b-key"]


@pytest.mark.asyncio
async def test_namespace_stats_are_isolated():
    """Hits/misses/size stats must be reported per namespace."""
    backing = MemoryBlock(None, {"max_size": 1000, "default_ttl": 3600})

    block_a = MemoryNamespaceProxy(backing, "block:a")
    block_b = MemoryNamespaceProxy(backing, "block:b")

    await block_a.process({"action": "set", "key": "x", "value": 1})
    await block_a.process({"action": "get", "key": "x"})
    await block_b.process({"action": "get", "key": "missing"})

    a_stats = await block_a.process({"action": "stats"})
    b_stats = await block_b.process({"action": "stats"})

    assert a_stats["size"] == 1
    assert a_stats["hits"] == 1
    assert a_stats["misses"] == 0

    assert b_stats["size"] == 0
    assert b_stats["hits"] == 0
    assert b_stats["misses"] == 1


@pytest.mark.asyncio
async def test_default_memory_block_remains_backward_compatible():
    """A MemoryBlock created without an explicit namespace still behaves globally-ish."""
    memory = MemoryBlock(None, {"max_size": 1000, "default_ttl": 3600})

    await memory.process({"action": "set", "key": "foo", "value": "bar"})
    result = await memory.process({"action": "keys"})
    assert "foo" in result["keys"]

    result = await memory.process({"action": "get", "key": "foo"})
    assert result["hit"] is True
    assert result["value"] == "bar"
