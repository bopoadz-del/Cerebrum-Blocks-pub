#!/usr/bin/env python3
"""
Adapter for Cerebrum block: aviation_ops_kit
"""

import asyncio

from app.blocks.aviation_ops_kit import AviationOpsKitBlock


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """Execute the aviation_ops_kit block."""
    instance = AviationOpsKitBlock()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.process(input_data, params))
    if envelope.get("status") in ("error", "refused"):
        raise RuntimeError(envelope.get("error") or "aviation_ops_kit block failed")
    return envelope.get("result", envelope)
