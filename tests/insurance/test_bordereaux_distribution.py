"""Tests for insurance bordereaux ingest and distribution analytics blocks."""

import pytest

from app.blocks.bordereaux_ingest import BordereauxIngestBlock
from app.blocks.distribution_analytics import DistributionAnalyticsBlock


@pytest.fixture
def bordereaux_block():
    return BordereauxIngestBlock()


@pytest.fixture
def analytics_block():
    return DistributionAnalyticsBlock()


@pytest.mark.asyncio
async def test_bordereaux_ingest_normalizes_csv_and_reports_errors(bordereaux_block):
    csv_payload = """policy_no,producer_code,LOB,period,premium,channel,commission
POL-1001,brk-ny-01,property,2026-01,"120,000",broker,14400
POL-1002,mga-ca-09,cyber,01/2026,85000,mga,12750
,brk-tx-02,property,2026-13,not-a-number,broker,100
"""

    result = await bordereaux_block.process(csv_payload, {"action": "normalize"})

    assert result["status"] == "error"
    assert result["detected_format"] == "csv"
    assert result["accepted_count"] == 2
    assert result["rejected_count"] == 1
    assert result["normalized_records"][0] == {
        "policy_no": "POL-1001",
        "producer_code": "BRK-NY-01",
        "lob": "PROPERTY",
        "period": "2026-01",
        "premium": 120000.0,
        "channel": "broker",
        "commission": 14400.0,
    }
    assert {error["field"] for error in result["validation_errors"]} == {
        "policy_no",
        "period",
        "premium",
    }


@pytest.mark.asyncio
async def test_bordereaux_simulate_webhook_is_deterministic(bordereaux_block):
    payload = {
        "carrier": "Simulated Mutual",
        "rows": [
            {
                "policy_number": "POL-2001",
                "producer": "agent-01",
                "line_of_business": "auto",
                "month": "2026-02-01",
                "gwp": "45000",
                "distribution_channel": "direct",
            }
        ],
    }

    first = await bordereaux_block.process(payload, {"action": "simulate_webhook"})
    second = await bordereaux_block.process(payload, {"action": "simulate_webhook"})

    assert first["status"] == "success"
    assert first["source"] == "simulated_carrier_feed"
    assert first["simulated"] is True
    assert first["external_api_calls"] == 0
    assert first["feed_id"] == second["feed_id"]
    assert first["normalized_records"][0]["period"] == "2026-02"


@pytest.mark.asyncio
async def test_distribution_analytics_summary_benchmark_and_trend(analytics_block):
    records = [
        {
            "policy_no": "POL-1001",
            "producer_code": "BRK-NY-01",
            "period": "2026-01",
            "premium": 120000,
            "channel": "broker",
            "commission": 14400,
            "expiring_premium": 100000,
            "renewal_premium": 120000,
        },
        {
            "policy_no": "POL-1002",
            "producer_code": "MGA-CA-09",
            "period": "2026-01",
            "premium": 80000,
            "channel": "mga",
            "commission": 12000,
            "expiring_premium": 100000,
            "renewal_premium": 80000,
        },
        {
            "policy_no": "POL-1001",
            "producer_code": "BRK-NY-01",
            "period": "2026-02",
            "premium": 130000,
            "channel": "broker",
            "commission": 15600,
        },
    ]

    summary = await analytics_block.process({"normalized_records": records}, {"action": "summary"})

    assert summary["status"] == "success"
    assert summary["metrics"]["total_gwp"] == 330000.0
    assert summary["metrics"]["gwp_by_channel"] == {
        "broker": 250000.0,
        "mga": 80000.0,
    }
    assert summary["metrics"]["commission_ratio"] == 0.1273
    assert summary["metrics"]["producer_productivity"]["average_gwp_per_producer"] == 165000.0
    assert summary["metrics"]["retention_proxy"] == {
        "value": 1.0,
        "basis": "renewal_premium_over_expiring_premium",
    }

    benchmark = await analytics_block.process(
        {"normalized_records": records, "benchmarks": {"commission_ratio": 0.12, "retention_proxy": 0.9}},
        {"action": "benchmark"},
    )
    assert benchmark["comparisons"]["commission_ratio"]["delta"] == 0.0073
    assert benchmark["comparisons"]["retention_proxy"]["meets_benchmark"] is True

    trend = await analytics_block.process({"normalized_records": records}, {"action": "trend"})
    assert [item["period"] for item in trend["series"]] == ["2026-01", "2026-02"]
    assert trend["trend"]["gwp_change"] == -70000.0
    assert trend["trend"]["gwp_direction"] == "down"
