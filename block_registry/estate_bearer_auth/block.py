#!/usr/bin/env python3
"""
Auto-generated adapter for Cerebrum block: estate_bearer_auth
Wraps app.blocks.estate_bearer_auth into a synchronous run() function.
"""

import asyncio
from app.blocks.estate_bearer_auth import EstateBearerAuthBlock


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    instance = EstateBearerAuthBlock()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") == "error":
        inner = envelope.get("result", {})
        message = envelope.get("error") or (
            inner.get("error") if isinstance(inner, dict) else str(inner)
        )
        raise RuntimeError(message or "estate_bearer_auth block failed")
    return envelope.get("result", envelope)
