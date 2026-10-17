#!/usr/bin/env python3
"""
Adapter for Cerebrum block: ibm_maximo_connector
"""

import asyncio

from app.blocks.ibm_maximo_connector import IbmMaximoConnectorBlock


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """Execute the ibm_maximo_connector block."""
    instance = IbmMaximoConnectorBlock()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") in ("error", "refused"):
        raise RuntimeError(envelope.get("error") or "ibm_maximo_connector block failed")
    return envelope.get("result", envelope)
