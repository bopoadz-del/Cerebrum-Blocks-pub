#!/usr/bin/env python3
"""
Adapter for Cerebrum block: evidence_or_refuse
"""

import asyncio

from app.blocks.evidence_or_refuse import EvidenceOrRefuseBlock


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """Execute the evidence_or_refuse block."""
    instance = EvidenceOrRefuseBlock()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") in ("error", "refused"):
        raise RuntimeError(envelope.get("error") or "evidence_or_refuse block failed")
    return envelope.get("result", envelope)
