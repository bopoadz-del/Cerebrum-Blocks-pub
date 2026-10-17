"""Tests for the capability-enforcing block proxy."""

from __future__ import annotations

import pytest

from app.core.block_capabilities import BlockCapabilities
from app.core.block_proxy import CapabilityProxy


class _FakeBlock:
    name = "fake"

    async def execute(self, input_data, params):
        return {"status": "ok", "input": input_data, "params": params}

    async def process(self, input_data, params):
        return {"status": "processed"}


@pytest.mark.asyncio
async def test_safe_proxy_delegates_execute():
    proxy = CapabilityProxy(_FakeBlock(), BlockCapabilities())
    result = await proxy.execute("hello", {"k": "v"})
    assert result["status"] == "ok"
    assert result["input"] == "hello"


@pytest.mark.asyncio
async def test_unsafe_proxy_rejects_in_process_execute():
    proxy = CapabilityProxy(_FakeBlock(), BlockCapabilities(network=True))
    with pytest.raises(RuntimeError) as exc_info:
        await proxy.execute("hello", {})
    assert "out-of-process" in str(exc_info.value)


@pytest.mark.asyncio
async def test_unsafe_proxy_rejects_in_process_process():
    proxy = CapabilityProxy(_FakeBlock(), BlockCapabilities(filesystem=True))
    with pytest.raises(RuntimeError) as exc_info:
        await proxy.process("hello", {})
    assert "out-of-process" in str(exc_info.value)


def test_proxy_requires_out_of_process():
    safe = CapabilityProxy(_FakeBlock(), BlockCapabilities())
    unsafe = CapabilityProxy(_FakeBlock(), BlockCapabilities(imports=["os"]))
    assert not safe.requires_out_of_process
    assert unsafe.requires_out_of_process


def test_proxy_allows_dependency():
    proxy = CapabilityProxy(_FakeBlock(), BlockCapabilities(blocks=["memory"]))
    assert proxy.allows_dependency("memory")
    assert not proxy.allows_dependency("auth")


def test_proxy_attribute_delegation():
    proxy = CapabilityProxy(_FakeBlock(), BlockCapabilities())
    assert proxy.name == "fake"
