#!/usr/bin/env python3
"""
Adapter for Cerebrum block: power_bi_connector
"""

import asyncio

from app.blocks.power_bi_connector import PowerBiConnectorBlock


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """Execute the power_bi_connector block."""
    instance = PowerBiConnectorBlock()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") in ("error", "refused"):
        raise RuntimeError(envelope.get("error") or "power_bi_connector block failed")
    return envelope.get("result", envelope)
