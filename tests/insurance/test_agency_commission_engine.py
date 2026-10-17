"""Tests for the deterministic agency commission engine."""

import pytest

from app.blocks.agency_commission_engine import AgencyCommissionEngineBlock


@pytest.mark.asyncio
async def test_calculate_life_fyc_with_hierarchy_overrides():
    block = AgencyCommissionEngineBlock()

    out = await block.process(
        {
            "operation": "calculate",
            "product_type": "life_fyc",
            "premium": 10000,
            "issue_date": "2026-01-15",
            "agent_level": "senior",
            "hierarchy": [
                {"agent_id": "mgr-1", "level": "agency_manager"},
                {"agent_id": "rd-1", "level": "regional_director"},
            ],
        }
    )

    assert out["status"] == "success"
    assert out["schedule_key"] == "life_fyc"
    assert out["base_commission"]["rate_pct"] == 90.0
    assert out["base_commission"]["amount"] == 9000.0
    assert out["override_total"] == 750.0
    assert out["total_commission"] == 9750.0
    assert out["net_commission"] == 9750.0


@pytest.mark.asyncio
async def test_apply_chargeback_prorates_pc_commission():
    block = AgencyCommissionEngineBlock()

    out = await block.process(
        {
            "operation": "apply_chargeback",
            "product_type": "pc_new",
            "original_commission": 1200,
            "effective_date": "2026-01-01",
            "cancellation_date": "2026-01-26",
            "term_days": 100,
        }
    )

    assert out["status"] == "success"
    assert out["schedule_key"] == "pc_new"
    assert out["days_in_force"] == 25
    assert out["chargeback_rate_pct"] == 75.0
    assert out["chargeback_amount"] == 900.0
    assert out["net_commission_after_chargeback"] == 300.0


@pytest.mark.asyncio
async def test_preview_override_calculates_upline_amounts():
    block = AgencyCommissionEngineBlock()

    out = await block.process(
        {
            "operation": "preview_override",
            "product_type": "pc_new",
            "premium": 5000,
            "issue_date": "2026-02-01",
            "hierarchy": [
                {"agent_id": "mgr-1", "level": "agency_manager"},
                {"agent_id": "rd-1", "level": "regional_director"},
                {"agent_id": "bd-1", "level": "broker_dealer"},
            ],
        }
    )

    assert out["status"] == "success"
    assert out["schedule_key"] == "pc_new"
    assert out["override_total"] == 175.0
    assert [row["amount"] for row in out["overrides"]] == [100.0, 50.0, 25.0]
    assert [row["rate_pct"] for row in out["overrides"]] == [2.0, 1.0, 0.5]
