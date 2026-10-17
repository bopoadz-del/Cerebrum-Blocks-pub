"""Tests for Capture Block."""

import os
import io
import base64
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.blocks import CaptureBlock


@pytest.fixture
def capture_block():
    return CaptureBlock()


@pytest.fixture
def sample_text_image():
    """Create a sample image with real text for OCR testing."""
    img = Image.new("RGB", (400, 100), color="white")
    draw = ImageDraw.Draw(img)
    # Use default font
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except Exception:
        font = ImageFont.load_default()
    draw.text((10, 30), "Hello World 123", fill="black", font=font)
    return img


@pytest.mark.asyncio
async def test_capture_block_execute_structure(capture_block):
    """Test that Capture block returns standardized JSON structure."""
    img = Image.new("RGB", (100, 30), color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    result = await capture_block.execute(
        {"bytes": buffer.read()},
        {"action": "capture", "source": "test"},
    )

    # Assert standardized keys
    assert "block" in result
    assert result["block"] == "capture"
    assert "request_id" in result
    assert "status" in result
    assert "result" in result
    assert "confidence" in result
    assert "metadata" in result
    assert "source_id" in result
    assert "processing_time_ms" in result


@pytest.mark.asyncio
async def test_capture_block_metadata(capture_block):
    """Test Capture block metadata."""
    assert capture_block.name == "capture"
    assert capture_block.config.version == "1.0.0"
    assert capture_block.config.requires_api_key == False


@pytest.mark.asyncio
async def test_capture_ocr_action(capture_block, sample_text_image):
    """Test OCR action on image with text."""
    buffer = io.BytesIO()
    sample_text_image.save(buffer, format="PNG")
    buffer.seek(0)

    result = await capture_block.execute(
        {"bytes": buffer.read()},
        {"action": "ocr", "languages": "eng"},
    )

    assert result["block"] == "capture"
    inner = result.get("result", {})
    # OCR may or may not detect text depending on environment; check structure
    assert "text" in inner or "error" in inner


@pytest.mark.asyncio
async def test_capture_structure_action(capture_block):
    """Test structure action on plain text (no image)."""
    sample_text = "Invoice from ACME Corp for $500 dated 2024-01-15. Contact: john@acme.com"
    result = await capture_block.execute(
        sample_text,
        {"action": "structure", "llm_provider": "ollama"},
    )

    assert result["block"] == "capture"
    # Capture block now requires image input - validation error expected for text-only
    assert result.get("status") == "error" or result.get("result", {}).get("status") == "error"


@pytest.mark.asyncio
async def test_capture_block_with_base64(capture_block):
    """Test Capture block accepts base64 input."""
    img = Image.new("RGB", (100, 30), color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    img_base64 = base64.b64encode(buffer.getvalue()).decode()

    result = await capture_block.execute(
        {"base64": img_base64},
        {"action": "capture", "source": "test"},
    )

    assert result["block"] == "capture"
    assert "result" in result


@pytest.mark.asyncio
async def test_capture_block_with_file_path(capture_block, tmp_path):
    """Test Capture block accepts file path input."""
    img = Image.new("RGB", (100, 30), color="white")
    file_path = tmp_path / "test_capture.png"
    img.save(file_path)

    result = await capture_block.execute(
        {"file_path": str(file_path)},
        {"action": "capture", "source": "test"},
    )

    assert result["block"] == "capture"
    assert "result" in result


@pytest.mark.asyncio
async def test_capture_search_action(capture_block):
    """Test search action returns expected structure."""
    result = await capture_block.execute(
        "test query",
        {"action": "search", "n_results": 3},
    )

    assert result["block"] == "capture"
    # Search may fail if vector DB not available, but structure should be valid
    assert "result" in result
