#!/usr/bin/env python3
"""
Auto-generated adapter for Cerebrum block: aviation_loyalty_kit
Wraps app.blocks.aviation_loyalty_kit into a synchronous run() function.
"""

import asyncio
from app.blocks.aviation_loyalty_kit import AviationLoyaltyKitBlock


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
    Execute the aviation_loyalty_kit block.
    Accepts keyword args matching the block's inputs/params.
    Returns the standardized block result payload.
    """
    instance = AviationLoyaltyKitBlock()

    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}

    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") == "error":
        inner = envelope.get("result", {})
        message = envelope.get("error") or (
            inner.get("error") if isinstance(inner, dict) else str(inner)
        )
        raise RuntimeError(message or "aviation_loyalty_kit block failed")

    return envelope.get("result", envelope)
