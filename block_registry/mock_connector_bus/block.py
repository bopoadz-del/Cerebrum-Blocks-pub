#!/usr/bin/env python3
"""
Adapter for Cerebrum block: mock_connector_bus
"""

import asyncio

from app.blocks.mock_connector_bus import MockConnectorBusBlock


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """Execute the mock_connector_bus block."""
    instance = MockConnectorBusBlock()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") in ("error", "refused"):
        raise RuntimeError(envelope.get("error") or "mock_connector_bus block failed")
    return envelope.get("result", envelope)
