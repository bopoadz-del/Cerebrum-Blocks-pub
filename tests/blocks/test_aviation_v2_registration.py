"""Smoke tests for the existing aviation_v2 block."""

import pytest

from app.blocks import BLOCK_REGISTRY
from app.blocks.aviation_v2 import AviationBlockV2


def test_aviation_v2_is_registered():
    assert "aviation_v2" in BLOCK_REGISTRY
    assert BLOCK_REGISTRY["aviation_v2"].__name__ == "AviationBlockV2"


@pytest.mark.asyncio
async def test_aviation_v2_analyzes_maintenance_log():
    block = AviationBlockV2()
    text = (
        "Aircraft N123AB MSN 45678. Maintenance check completed per Part 145. "
        "Total flight hours 12450. Airworthiness directive 2024-01 complied with."
    )
    result = await block.process({"text": text}, params={"document_type": "maintenance_log"})

    assert result["document_type"] == "maintenance_log"
    assert any(e["type"] == "aircraft_registrations" for e in result["entities"].get("aircraft_registrations", []))
    assert result["compliance_flags"]["easa"]["detected"] is True


@pytest.mark.asyncio
async def test_aviation_v2_returns_empty_for_no_text():
    block = AviationBlockV2()
    result = await block.process({}, params={})
    assert result["status"] == "error"
    assert "No text provided" in result.get("error", "")
