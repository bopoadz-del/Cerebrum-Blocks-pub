"""Tests for video metadata ingest block."""

import pytest

from app.blocks.video_metadata_ingest import VideoMetadataIngestBlock
from app.core.video_store import InMemoryVideoStore, reset_video_store


@pytest.fixture
def ingest_block():
    reset_video_store(InMemoryVideoStore())
    return VideoMetadataIngestBlock()


@pytest.fixture
def sample_metadata():
    return {
        "source_id": "test-edge",
        "camera_id": "cam-lobby",
        "zones": [{"zone_id": "lobby", "count": 10, "capacity": 50}],
        "anomalies": [
            {
                "anomaly_type": "loitering",
                "severity": "medium",
                "confidence": 0.8,
            }
        ],
    }


@pytest.mark.asyncio
async def test_ingest_stores_metadata(ingest_block, sample_metadata):
    result = await ingest_block.execute(sample_metadata, {"action": "ingest"})
    assert result["status"] == "success"
    inner = result["result"]
    assert inner["stored"] is True
    assert inner["anomaly_count"] == 1
    assert inner.get("trigger_recommended") is True


@pytest.mark.asyncio
async def test_ingest_rejects_invalid_payload(ingest_block):
    result = await ingest_block.execute({"zones": "not-a-list"}, {"action": "ingest"})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_list_by_camera(ingest_block, sample_metadata):
    await ingest_block.process(sample_metadata, {"action": "ingest"})
    listed = await ingest_block.process(
        {"camera_id": "cam-lobby"}, {"action": "list"}
    )
    assert listed["status"] == "success"
    assert listed["count"] >= 1


@pytest.mark.asyncio
async def test_health(ingest_block):
    result = await ingest_block.process(None, {"action": "health"})
    assert result["status"] == "healthy"
