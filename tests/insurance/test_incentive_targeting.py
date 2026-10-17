import json
from pathlib import Path

import pytest

from app.blocks.incentive_targeting import IncentiveTargetingBlock


@pytest.mark.asyncio
async def test_target_uses_formula_like_eligibility_rules():
    block = IncentiveTargetingBlock()

    result = await block.process(
        {
            "operation": "target",
            "producer": {
                "producer_id": "p-growth",
                "production": 120000,
                "growth_pct": 10,
                "retention_rate": 0.91,
                "loss_ratio": 0.50,
                "compliance_issues": 0,
                "strategic_products": 2,
            },
        }
    )

    assert result["status"] == "success"
    assert result["eligible"] is True
    assert result["recommended_bonus"] > 0
    assert "production *" in result["formula"]
    assert "not ML" in result["methodology"]


@pytest.mark.asyncio
async def test_rank_and_simulate_budget_prioritize_eligible_producers():
    block = IncentiveTargetingBlock()
    producers = [
        {
            "producer_id": "eligible",
            "production": 180000,
            "growth_pct": 15,
            "retention_rate": 0.93,
            "loss_ratio": 0.45,
            "strategic_products": 3,
        },
        {
            "producer_id": "blocked",
            "production": 250000,
            "growth_pct": 20,
            "retention_rate": 0.95,
            "loss_ratio": 0.40,
            "compliance_issues": 1,
        },
    ]

    ranked = await block.process({"operation": "rank_producers", "producers": producers})
    assert ranked["ranked_producers"][0]["rank_score"] >= ranked["ranked_producers"][1]["rank_score"]
    assert all("rank_factors" in item for item in ranked["ranked_producers"])

    simulated = await block.process({"operation": "simulate_budget", "budget": 1000, "producers": producers})
    eligible_allocation = next(item for item in simulated["allocations"] if item["producer_id"] == "eligible")
    blocked_allocation = next(item for item in simulated["allocations"] if item["producer_id"] == "blocked")

    assert simulated["allocated"] <= simulated["budget"]
    assert eligible_allocation["allocated_bonus"] > 0
    assert blocked_allocation["allocated_bonus"] == 0


def test_incentive_targeting_registry_bundle_and_playbook_entries():
    root = Path(__file__).resolve().parents[2]
    registry = json.loads((root / "block_registry" / "incentive_targeting" / "block.json").read_text())
    manifest = json.loads((root / "block_store" / "kits" / "insurance" / "manifest.json").read_text())

    # Phase 5: block signing operates — the registry entry carries a
    # valid platform signature (was empty while signing was parked).
    assert registry["signature"], "block must be signed"
    from app.core.publisher_registry import BlockVerifier
    verdict = BlockVerifier().verify_block(
        root / "block_registry" / registry["id"]
    )
    assert verdict["verified"], verdict.get("reason")
    assert "incentive_targeting" in manifest["blocks"]
    assert "app/data/incentive_playbook.json" not in manifest["data"]
    parked = (
        root / "block_store" / "kits" / "insurance" / "parked" / "incentive_playbook.json"
    )
    assert parked.exists()
    assert json.loads(parked.read_text())["provenance"]["parked"] is True
    assert (root / "block_store" / "kits" / "insurance" / "bundle" / "app" / "blocks" / "incentive_targeting.py").exists()
