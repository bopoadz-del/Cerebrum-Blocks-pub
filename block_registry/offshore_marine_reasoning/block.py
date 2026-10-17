#!/usr/bin/env python3
"""
Adapter for Cerebrum block: offshore_marine_reasoning
"""

import asyncio

from app.blocks.offshore_marine_reasoning import OffshoreMarineReasoningBlock


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """Execute the offshore_marine_reasoning block."""
    instance = OffshoreMarineReasoningBlock()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") in ("error", "refused"):
        raise RuntimeError(envelope.get("error") or "offshore_marine_reasoning block failed")
    return envelope.get("result", envelope)
