#!/usr/bin/env python3
"""
Adapter for Cerebrum block: validation_pipeline_fork
"""

import asyncio

from app.blocks.validation_pipeline_fork import ValidationPipelineForkBlock


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """Execute the validation_pipeline_fork block."""
    instance = ValidationPipelineForkBlock()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") in ("error", "refused"):
        raise RuntimeError(envelope.get("error") or "validation_pipeline_fork block failed")
    return envelope.get("result", envelope)
