#!/usr/bin/env python3
"""
Adapter for Cerebrum block: og_construction_kit
"""

import asyncio

from app.blocks.og_construction_kit import OgConstructionKitBlock


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """Execute the og_construction_kit block."""
    instance = OgConstructionKitBlock()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.process(input_data, params))
    if envelope.get("status") in ("error", "refused"):
        raise RuntimeError(envelope.get("error") or "og_construction_kit block failed")
    return envelope.get("result", envelope)
