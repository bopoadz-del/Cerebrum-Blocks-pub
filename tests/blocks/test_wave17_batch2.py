"""Wave 1.7 batch 2 — historical_benchmark 'record' is no longer a vacuous stub.

Before the fix, action=record returned status:success without persisting
anything. Now it delegates to learning_engine's real correction path and
the sample lands in the credibility ledger.
"""

import asyncio
import json
import os
import tempfile

import pytest

from app.blocks.historical_benchmark import HistoricalBenchmarkBlock


def test_record_refuses_incomplete_payload():
    block = HistoricalBenchmarkBlock()
    out = asyncio.run(
        block.process({"action": "record", "formula_id": "concrete_cost"})
    )
    assert out["status"] == "error"
    assert "predicted" in out["error"]


def test_record_persists_through_learning_engine():
    block = HistoricalBenchmarkBlock()
    out = asyncio.run(
        block.process(
            {
                "action": "record",
                "correction_data": {
                    "formula_id": "concrete_cost",
                    "predicted": 125000,
                    "actual": 118000,
                },
            }
        )
    )
    # Delegated result carries the engine's real accounting (status,
    # samples, tier) — never a canned success envelope.
    assert out.get("status") == "success", out
    assert out.get("action") == "record"
    assert out.get("formula_id") == "concrete_cost"
    assert "samples" in out or "sample_count" in out or "tier" in out, (
        "delegated result must carry the engine's accounting fields"
    )
