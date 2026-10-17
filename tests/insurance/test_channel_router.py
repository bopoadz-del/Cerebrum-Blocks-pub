import json
from pathlib import Path

import pytest

from app.blocks.channel_router import ChannelRouterBlock


@pytest.mark.asyncio
async def test_route_recommends_mga_for_specialty_complex_risk():
    block = ChannelRouterBlock()

    result = await block.process(
        {
            "operation": "route",
            "account": {
                "line_of_business": "cyber",
                "premium": 90000,
                "complexity": "high",
                "specialty_risk": True,
            },
        }
    )

    assert result["status"] == "success"
    assert result["recommended_channel"] == "mga"
    assert result["score"] == 100
    assert any(item["factor"] == "specialty_risk" for item in result["ranked_channels"][0]["factors"])
    assert "not trained ML" in result["methodology"]


@pytest.mark.asyncio
async def test_list_channels_and_score_channels_are_explainable():
    block = ChannelRouterBlock()

    listed = await block.process({"operation": "list_channels"})
    assert {item["channel"] for item in listed["channels"]} == {"agency", "direct", "mga", "partner"}

    scored = await block.process(
        {
            "operation": "score_channels",
            "account": {
                "line_of_business": "personal_auto",
                "premium": 1200,
                "complexity": "low",
                "digital_preference": True,
                "speed_priority": True,
            },
        }
    )

    assert scored["ranked_channels"][0]["channel"] == "direct"
    assert scored["ranked_channels"][0]["explanation"]
    assert all("factors" in item for item in scored["ranked_channels"])


def test_channel_router_registry_and_insurance_manifest_entries():
    root = Path(__file__).resolve().parents[2]
    registry = json.loads((root / "block_registry" / "channel_router" / "block.json").read_text())
    manifest = json.loads((root / "block_store" / "kits" / "insurance" / "manifest.json").read_text())

    # Phase 5: block signing operates — the registry entry carries a
    # valid platform signature (was empty while signing was parked).
    assert registry["signature"], "block must be signed"
    from app.core.publisher_registry import BlockVerifier
    verdict = BlockVerifier().verify_block(
        root / "block_registry" / registry["id"]
    )
    assert verdict["verified"], verdict.get("reason")
    assert registry["permissions"] == {"network": False, "filesystem": False, "imports": [], "blocks": []}
    assert "channel_router" in manifest["blocks"]
    assert (root / "block_store" / "kits" / "insurance" / "bundle" / "app" / "blocks" / "channel_router.py").exists()
