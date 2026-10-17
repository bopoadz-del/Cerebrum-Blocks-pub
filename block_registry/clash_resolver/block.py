#!/usr/bin/env python3
"""
Adapter for Cerebrum block: clash_resolver
Wraps app.blocks.clash_resolver.ClashResolverBlock.execute() into a synchronous run() function.
"""

import asyncio

from app.blocks.clash_resolver import ClashResolverBlock


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
    Execute the clash_resolver block.
    Accepts keyword args matching the block's inputs/params.
    Returns the standardized block result payload.
    """
    instance = ClashResolverBlock()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") == "error":
        raise RuntimeError(envelope.get("error") or "clash_resolver block failed")
    return envelope.get("result", envelope)
