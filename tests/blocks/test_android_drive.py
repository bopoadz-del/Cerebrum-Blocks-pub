"""Tests for Android Drive Block."""

import pytest
from app.blocks import AndroidDriveBlock


@pytest.fixture
def android_drive_block():
    return AndroidDriveBlock()


@pytest.mark.asyncio
async def test_android_drive_block_execute_structure(android_drive_block):
    """Test that Android Drive block returns standardized JSON structure."""
    result = await android_drive_block.execute(
        None,
        {"operation": "list"}
    )
    
    # Assert standardized keys
    assert "block" in result
    assert result["block"] == "android_drive"
    assert "request_id" in result
    assert "status" in result
    assert "result" in result
    assert "confidence" in result
    assert "metadata" in result
    assert "source_id" in result
    assert "processing_time_ms" in result


@pytest.mark.asyncio
async def test_android_drive_block_metadata(android_drive_block):
    """Test Android Drive block metadata."""
    assert android_drive_block.name == "android_drive"
    assert android_drive_block.config.version == "1.0"
    assert "uri" in android_drive_block.config.supported_outputs
    assert "metadata" in android_drive_block.config.supported_outputs
    assert android_drive_block.config.requires_api_key == False


@pytest.mark.asyncio
async def test_android_drive_block_get_paths_is_honest(android_drive_block):
    """get_paths must not fabricate device paths — no integration exists."""
    result = await android_drive_block.execute(
        None,
        {"operation": "get_paths"}
    )

    assert result["block"] == "android_drive"
    assert result["result"]["operation"] == "get_paths"
    assert result["result"]["status"] != "success"
    assert result["result"]["error"] == "not_implemented"
    assert "paths" not in result["result"]


@pytest.mark.asyncio
async def test_android_drive_block_list_is_honest(android_drive_block):
    """list must not claim the integration is ready — none is wired."""
    result = await android_drive_block.execute(
        None,
        {"operation": "list", "folder_path": "/sdcard"}
    )

    assert result["block"] == "android_drive"
    assert result["result"]["status"] != "success"
    assert result["result"]["error"] == "not_implemented"
