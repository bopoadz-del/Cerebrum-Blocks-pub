"""Tests for video anomaly trigger block."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.blocks.video_anomaly_trigger import VideoAnomalyTriggerBlock


@pytest.fixture
def trigger_block():
    block = VideoAnomalyTriggerBlock()
    mock_notif = MagicMock()
    mock_notif.process = AsyncMock(return_value={"status": "success", "channel": "webhook", "sent": True})
    block.wire("notification", mock_notif)
    return block


@pytest.fixture
def metadata_with_anomaly():
    return {
        "source_id": "edge-1",
        "camera_id": "pool-cam",
        "anomalies": [
            {
                "anomaly_type": "intrusion",
                "severity": "critical",
                "confidence": 0.95,
            }
        ],
    }


@pytest.mark.asyncio
async def test_evaluate_triggers_on_critical(trigger_block, metadata_with_anomaly):
    result = await trigger_block.execute(
        {"metadata": metadata_with_anomaly, "url": "https://hooks.test/alert"},
        {"action": "evaluate", "channel": "webhook"},
    )
    assert result["status"] == "success"
    inner = result["result"]
    assert inner["triggered"] is True
    assert len(inner["anomalies"]) == 1
    assert "workflow_payload" in inner


@pytest.mark.asyncio
async def test_evaluate_skips_low_severity(trigger_block, metadata_with_anomaly):
    metadata_with_anomaly["anomalies"][0]["severity"] = "low"
    result = await trigger_block.execute(
        metadata_with_anomaly,
        {"action": "evaluate", "min_severity": "high"},
    )
    inner = result["result"]
    assert inner["triggered"] is False


@pytest.mark.asyncio
async def test_no_notification_when_disabled(trigger_block, metadata_with_anomaly):
    result = await trigger_block.execute(
        {"metadata": metadata_with_anomaly},
        {"action": "evaluate", "send_notification": "false"},
    )
    inner = result["result"]
    assert inner["triggered"] is True
    assert inner.get("notification") is None
