#!/usr/bin/env python3
"""
Adapter for Cerebrum block: bcf_export
Wraps app.blocks.bcf_export.BcfExportBlock.execute() into a synchronous run() function.
"""

import asyncio

from app.blocks.bcf_export import BcfExportBlock


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
    Execute the bcf_export block.
    Accepts keyword args matching the block's inputs/params.
    Returns the standardized block result payload.
    """
    instance = BcfExportBlock()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") == "error":
        raise RuntimeError(envelope.get("error") or "bcf_export block failed")
    return envelope.get("result", envelope)
