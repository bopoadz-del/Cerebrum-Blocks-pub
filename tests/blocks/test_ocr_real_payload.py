"""OCRBlock.process — entry-point coverage, and the wall it runs into.

Why this file exists
--------------------
``tests/blocks/test_ocr.py`` drives ``execute`` and asserts only the
UniversalBlock envelope keys, so the control-delete in
``scripts/certify_block.py`` gutted ``OCRBlock.process`` and that suite stayed
GREEN.

What this file found, and what fixed it
---------------------------------------
``OCRBlock.process`` could not reach a real artifact in this Store *at all*.
For any input that resolved to an existing file it called ``_process_image``,
whose first statement is ``_detect_markup``, whose first statement is

    from app.core.redline import detect_redlines, summarize_markup

— an unconditional import, outside the function's ``try``. Neither
``app.core.redline`` nor ``app.core.image_quality`` (imported a few lines later
for ``summarize_ocr_quality``) existed here: ``app/blocks/ocr.py`` had been
copied in without the two core modules it depends on. So every image and every
PDF raised ``ModuleNotFoundError`` before a single pixel was read, and
``UniversalBlock.execute`` swallowed it into a generic error envelope — which
is exactly why the block looked certifiable.

It surfaced outside the tests too: the Factory's CLONER walks the same imports
to build a product's runtime slice and refused the whole clone with
``runtime slice needs app/core/redline.py which does not exist in the Store
checkout`` — correctly, since vendoring ocr without it ships a latent
ImportError to the customer.

Both modules now exist (ported from The_Fork, where they were already
implemented and tested — see tests/core/test_redline.py and
tests/core/test_image_quality.py). The registry's earlier note blamed a missing
OCR fixture; the fixture was never the blocker.
``tests/fixtures/synthetic_tm_detail.pdf`` is a real 485 KB construction
drawing, and the tests at the bottom of this file now read it end to end.
"""

from __future__ import annotations

from pathlib import Path

from app.blocks.ocr import OCRBlock


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DRAWING = FIXTURES / "synthetic_tm_detail.pdf"


# ── the paths that do return a payload ─────────────────────────────────────


async def test_missing_file_reports_the_path_it_was_given():
    result = await OCRBlock().process({"file_path": "/tmp/no_such_scan.png"}, {})

    assert result["status"] == "error"
    assert result["error"] == "File not found: /tmp/no_such_scan.png"
    assert result["text"] == ""
    assert result["confidence"] == 0


async def test_bare_string_path_is_resolved_and_reported_by_name():
    """A bare string is treated as a path, not as prompt text."""
    result = await OCRBlock().process("/tmp/also_missing.tiff", {})

    assert result["status"] == "error"
    assert result["error"] == "File not found: /tmp/also_missing.tiff"


async def test_input_carrying_no_path_is_rejected_by_name():
    result = await OCRBlock().process({"language": "eng"}, {})

    assert result["status"] == "error"
    assert result["error"] == "No image provided"
    assert result["text"] == ""
    assert result["confidence"] == 0


async def test_a_pil_image_object_is_not_a_path_and_is_refused():
    """The block only accepts paths; an in-memory image is not one.

    tests/blocks/test_ocr.py passes ``{"image": <PIL.Image>}`` and asserts the
    envelope, which hides the fact that the block never looks at it.
    """
    from PIL import Image

    result = await OCRBlock().process({"image": Image.new("RGB", (40, 20))}, {})

    assert result["status"] == "error"
    assert result["error"] == "No image provided"


# ── the real drawing, read end to end ──────────────────────────────────────
#
# These replace the two defect pins this file opened with. Assertions are
# engine-independent on purpose: CI installs tesseract-ocr, this repo's
# requirements pin pytesseract and pymupdf, and a developer machine without
# the tesseract BINARY takes the PyMuPDF text-layer fallback instead. All
# three must agree, so nothing here asserts an engine name or a raw
# confidence number -- only that real text came out and the markup verdict is
# the one the pixels support.


async def test_real_drawing_is_read_and_yields_its_notes():
    assert DRAWING.is_file()

    result = await OCRBlock().process({"file_path": str(DRAWING)}, {})

    assert result["status"] == "success", result.get("error")
    assert result["word_count"] > 100, "a 485 KB drawing carries more than a caption"
    assert result["confidence"] > 0


def test_the_drawings_text_layer_carries_the_general_notes():
    """Deterministic on every machine: PyMuPDF reads the embedded text layer,
    no rasterising and no OCR engine, so the exact wording is assertable."""
    text = OCRBlock()._extract_pdf_text(str(DRAWING)).upper()

    assert "ALL DIMENSIONS ARE IN METERS" in text
    assert "INFRASTRUCTURE" in text


async def test_the_drawings_redlines_are_flagged_not_merged_into_the_text():
    """app.core.redline, measured on the real artifact rather than a synthetic
    one: this drawing is annotated, and the annotation is reported separately
    from the extracted text instead of being mangled into it."""
    result = await OCRBlock().process({"file_path": str(DRAWING)}, {})
    markup = result["markup"]

    assert markup["has_markup"] is True
    assert markup["region_count"] > 0
    assert 0 < markup["coverage"] < 1
    assert markup["caveat"] and "redlines" in markup["caveat"]
    # The whole point of flagging: the caveat text is not silently appended to
    # what the block reports as extracted document text.
    assert markup["caveat"] not in result["text"]


async def test_execute_wraps_the_success_in_the_block_envelope():
    """This used to assert that execute() MASKED a ModuleNotFoundError."""
    envelope = await OCRBlock().execute({"file_path": str(DRAWING)}, {})

    assert envelope["block"] == "ocr"
    assert envelope["status"] == "success", envelope
    assert envelope["result"]["text"].strip()
