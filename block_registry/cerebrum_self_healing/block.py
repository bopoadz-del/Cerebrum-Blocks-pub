#!/usr/bin/env python3
"""
Adapter for Cerebrum block: cerebrum_self_healing
"""

import asyncio

from app.blocks.cerebrum_self_healing import CerebrumSelfHealingBlock


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """Execute the cerebrum_self_healing block."""
    instance = CerebrumSelfHealingBlock()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") in ("error", "refused"):
        raise RuntimeError(envelope.get("error") or "cerebrum_self_healing block failed")
    return envelope.get("result", envelope)
