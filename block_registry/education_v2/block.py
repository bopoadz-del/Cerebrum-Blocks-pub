#!/usr/bin/env python3
"""
Adapter for Cerebrum block: education_v2
"""

import asyncio

from app.blocks.education_v2 import EducationBlockV2


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """Execute the education_v2 block."""
    instance = EducationBlockV2()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") == "error":
        raise RuntimeError(envelope.get("error") or "education_v2 block failed")
    return envelope.get("result", envelope)
