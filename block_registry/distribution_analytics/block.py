#!/usr/bin/env python3
"""Registry adapter for the distribution_analytics block."""

import asyncio
from app.blocks import get_block


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """Execute the distribution_analytics block."""
    block_cls = get_block("distribution_analytics")
    if block_cls is None:
        raise RuntimeError("distribution_analytics block is not loaded")
    instance = block_cls()

    input_data = kwargs.get("input", kwargs)
    params = {key: value for key, value in kwargs.items() if key != "input"}

    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") == "error":
        inner = envelope.get("result", {})
        message = inner.get("error") if isinstance(inner, dict) else str(inner)
        raise RuntimeError(message or "distribution_analytics block failed")
    return envelope.get("result", envelope)
