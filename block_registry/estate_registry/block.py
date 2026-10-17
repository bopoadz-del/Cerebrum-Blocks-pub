#!/usr/bin/env python3
"""
Auto-generated adapter for Cerebrum block: estate_registry
Wraps app.blocks.estate_registry into a synchronous run() function.
"""

import asyncio
from app.blocks.estate_registry import EstateRegistryBlock


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """
    Execute the estate_registry block.
    Accepts keyword args matching the block's inputs/params.
    Returns the standardized block result payload.
    """
    instance = EstateRegistryBlock()

    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}

    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") == "error":
        inner = envelope.get("result", {})
        message = envelope.get("error") or (
            inner.get("error") if isinstance(inner, dict) else str(inner)
        )
        raise RuntimeError(message or "estate_registry block failed")

    return envelope.get("result", envelope)
