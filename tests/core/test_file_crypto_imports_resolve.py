"""The lazy `from app.core.file_crypto import open_plaintext` imports must resolve.

Regression for a launch-audit follow-up finding (2026-08-02): Phase 1 (#53)
merged blocks whose read paths lazily import ``app.core.file_crypto``, but the
module itself lived only on an unmerged branch. On production main, every
execution of the image block's metadata path and the OCR block's process path
raised ``ModuleNotFoundError`` — and OCR is in the FREE tier's block
allowlist, so the platform's entry-tier functionality was dead on arrival.

A plain ``import app.core.file_crypto`` would not have caught this shape:
the imports are inside function bodies, so the break only surfaces when the
block actually runs. These tests drive the real call paths.
"""

import importlib

import pytest


def test_file_crypto_module_exists():
    mod = importlib.import_module("app.core.file_crypto")
    assert hasattr(mod, "open_plaintext")
    assert hasattr(mod, "read_document")
    assert hasattr(mod, "write_document")


def test_image_block_metadata_path_executes(tmp_path):
    """_pil_metadata performs the lazy import at call time — run it for real."""
    from PIL import Image as PIL_Image

    from app.blocks.image import _pil_metadata

    path = tmp_path / "probe.png"
    PIL_Image.new("RGB", (4, 3), color=(10, 20, 30)).save(path)

    meta = _pil_metadata(str(path))
    assert meta["width"] == 4
    assert meta["height"] == 3


@pytest.mark.asyncio
async def test_ocr_block_reaches_processing_not_modulenotfound(tmp_path):
    """The OCR execute path must get past the file_crypto import.

    OCR itself may fail further down (no tesseract in the test env) — that
    is fine and returns an error dict. What must never happen is
    ModuleNotFoundError before processing starts.
    """
    from PIL import Image as PIL_Image

    from app.blocks.ocr import OCRBlock

    path = tmp_path / "probe.png"
    PIL_Image.new("RGB", (12, 12), color=(255, 255, 255)).save(path)

    block = OCRBlock()
    try:
        result = await block.execute({"image_path": str(path)})
    except ModuleNotFoundError as exc:  # the exact production failure
        pytest.fail(f"OCR execute path raised ModuleNotFoundError: {exc}")
    assert isinstance(result, dict)
