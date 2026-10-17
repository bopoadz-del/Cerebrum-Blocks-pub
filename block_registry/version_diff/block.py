#!/usr/bin/env python3
"""
Adapter for Cerebrum block: version_diff
Wraps app.blocks.version_diff.VersionDiffBlock.execute() into a synchronous run() function.
"""

import asyncio

from app.blocks.version_diff import VersionDiffBlock


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
    Execute the version_diff block.
    Accepts keyword args matching the block's inputs/params.
    Returns the standardized block result payload.
    """
    instance = VersionDiffBlock()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") == "error":
        raise RuntimeError(envelope.get("error") or "version_diff block failed")
    return envelope.get("result", envelope)
