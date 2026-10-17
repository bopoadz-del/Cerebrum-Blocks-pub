"""Unimplemented capabilities must say so in the response a caller reads."""

import pytest

from app.blocks.android_drive import AndroidDriveBlock


@pytest.mark.asyncio
async def test_android_drive_does_not_fabricate_success():
    block = AndroidDriveBlock()
    result = await block.execute(None, {"operation": "get_paths"})
    body = result["result"]
    assert body.get("status") != "success", (
        "android_drive has no ADB/REST bridge — it must not claim success "
        f"with fabricated paths: {body}"
    )
    assert "not_implemented" in str(body)


@pytest.mark.asyncio
async def test_android_drive_list_does_not_fabricate_success():
    block = AndroidDriveBlock()
    result = await block.execute(None, {"operation": "list"})
    body = result["result"]
    assert body.get("status") != "success"
    assert "not_implemented" in str(body)
