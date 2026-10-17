import json
from pathlib import Path

import pytest

from app.blocks.attrition_scorer import AttritionScorerBlock


@pytest.mark.asyncio
async def test_score_returns_high_risk_with_factor_contributions():
    block = AttritionScorerBlock()

    result = await block.process(
        {
            "operation": "score",
            "producer": {
                "producer_id": "p-risky",
                "production_trend_pct": -30,
                "tenure_months": 4,
                "logins_last_30_days": 0,
                "complaint_count": 5,
                "missed_targets": 3,
                "open_service_tickets": 5,
            },
        }
    )

    assert result["status"] == "success"
    assert result["risk_band"] == "critical"
    assert result["score"] == 100
    assert {item["factor"] for item in result["factor_contributions"]} >= {
        "production_trend",
        "tenure",
        "login_frequency",
        "complaint_count",
    }
    assert "not trained ML" in result["methodology"]


@pytest.mark.asyncio
async def test_explain_and_batch_score_are_sorted():
    block = AttritionScorerBlock()

    explained = await block.process(
        {
            "operation": "explain",
            "producer": {
                "producer_id": "p-steady",
                "production_trend_pct": 20,
                "tenure_months": 60,
                "logins_last_30_days": 24,
                "complaint_count": 0,
                "nps": 9,
            },
        }
    )
    assert explained["risk_band"] == "low"
    assert "Main drivers" in explained["narrative"]

    batch = await block.process(
        {
            "operation": "batch_score",
            "producers": [
                {"producer_id": "low", "production_trend_pct": 20, "tenure_months": 60, "logins_last_30_days": 20},
                {"producer_id": "high", "production_trend_pct": -25, "tenure_months": 3, "logins_last_30_days": 0, "complaint_count": 4},
            ],
        }
    )

    assert [item["producer_id"] for item in batch["results"]] == ["high", "low"]


def test_attrition_scorer_registry_and_bundle_entries():
    root = Path(__file__).resolve().parents[2]
    registry = json.loads((root / "block_registry" / "attrition_scorer" / "block.json").read_text())
    manifest = json.loads((root / "block_store" / "kits" / "insurance" / "manifest.json").read_text())

    # Phase 5: block signing operates — the registry entry carries a
    # valid platform signature (was empty while signing was parked).
    assert registry["signature"], "block must be signed"
    from app.core.publisher_registry import BlockVerifier
    verdict = BlockVerifier().verify_block(
        root / "block_registry" / registry["id"]
    )
    assert verdict["verified"], verdict.get("reason")
    assert "attrition_scorer" in manifest["blocks"]
    assert "app/data/retention_playbook.json" not in manifest["data"]
    parked = (
        root / "block_store" / "kits" / "insurance" / "parked" / "retention_playbook.json"
    )
    assert parked.exists()
    assert json.loads(parked.read_text())["provenance"]["parked"] is True
    assert (root / "block_store" / "kits" / "insurance" / "bundle" / "app" / "blocks" / "attrition_scorer.py").exists()
