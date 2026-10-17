#!/usr/bin/env python3
"""
Adapter for Cerebrum block: mep_zoning
"""

import asyncio

from app.blocks.mep_zoning import MepZoningBlock


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """Execute the mep_zoning block."""
    instance = MepZoningBlock()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") in ("error", "refused"):
        raise RuntimeError(envelope.get("error") or "mep_zoning block failed")
    return envelope.get("result", envelope)
