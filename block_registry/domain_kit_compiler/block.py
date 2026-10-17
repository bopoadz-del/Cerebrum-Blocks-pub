#!/usr/bin/env python3
"""
Adapter for Cerebrum block: domain_kit_compiler
"""

import asyncio

from app.blocks.domain_kit_compiler import DomainKitCompilerBlock


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """Execute the domain_kit_compiler block."""
    instance = DomainKitCompilerBlock()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") in ("error", "refused"):
        raise RuntimeError(envelope.get("error") or "domain_kit_compiler block failed")
    return envelope.get("result", envelope)
