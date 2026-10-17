"""Tests for the OCR fallback added to ``app/blocks/pdf.py``.

Real-world test of the SPA on a scanned/vector construction drawing
returned near-empty output. The fix adds a tesseract OCR fallback
that fires when the text-density-per-page falls below 100 chars.

These tests are sandboxed: they synthesise tiny PDFs with PyMuPDF
and monkeypatch ``pytesseract`` so they run without a tesseract
binary on the host.
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
from typing import List

import pytest


# ── helpers ────────────────────────────────────────────────────────────────


def _make_text_pdf(path: str, body: str, pages: int = 1) -> None:
    """Write a normal text PDF — enough characters that the density check
    stays well above the 100 chars/page threshold."""
    import fitz

    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), body, fontsize=10)
    doc.save(path)
    doc.close()


def _make_scanned_pdf(path: str, pages: int = 1) -> None:
    """Write a 'scanned-style' PDF: a near-blank page with a tiny
    embedded image and no embedded text. The text-density gate
    will see well under 100 chars/page and trigger OCR."""
    import fitz
    from PIL import Image

    # Build a real, valid 4x4 white PNG via Pillow so PyMuPDF accepts it.
    img = Image.new("RGB", (4, 4), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        # No text at all — image-only page, like a real scan.
        page.insert_image(fitz.Rect(0, 0, 100, 100), stream=png_bytes)
    doc.save(path)
    doc.close()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if sys.version_info < (3, 10) else asyncio.run(coro)


# ── 1. Text-heavy PDF: OCR must NOT trigger ────────────────────────────────


def test_text_heavy_pdf_does_not_trigger_ocr(tmp_path, monkeypatch):
    from app.blocks import pdf as pdf_mod
    from app.blocks.pdf import PDFBlock

    pdf_path = str(tmp_path / "dense.pdf")
    # Pad each page with ~5KB of text so density-per-page is huge.
    body = ("LOREM IPSUM DOLOR SIT AMET " * 200).strip()
    _make_text_pdf(pdf_path, body, pages=2)

    called = {"ocr": False}

    def _spy(*args, **kwargs):
        called["ocr"] = True
        return None

    monkeypatch.setattr(pdf_mod, "_try_ocr_fallback", _spy)

    block = PDFBlock()
    result = asyncio.run(block.process(pdf_path))

    assert result["status"] == "success"
    assert called["ocr"] is False, "OCR should not run for dense text PDFs"
    assert result["engine"] in {"pdfplumber", "pypdf", "PyMuPDF"}
    # Body of text should round-trip — engines all see the inserted glyphs.
    assert "LOREM IPSUM" in result["text"]


# ── 2. Scanned PDF: OCR fallback fires and overrides the engine label ─────


def test_scanned_pdf_triggers_ocr_branch(tmp_path, monkeypatch):
    from app.blocks import pdf as pdf_mod
    from app.blocks.pdf import PDFBlock

    pdf_path = str(tmp_path / "scan.pdf")
    _make_scanned_pdf(pdf_path, pages=2)

    fake_ocr = "--- page 1 ---\n" + ("OCR EXTRACTED " * 50)

    def _fake_fallback(path, original_text, **kwargs):
        # Sanity: density gate should put us well below 100 chars/page.
        density = len(original_text.strip()) / max(2, 1)
        assert density < 100, f"density={density} should have stayed thin"
        return fake_ocr

    monkeypatch.setattr(pdf_mod, "_try_ocr_fallback", _fake_fallback)

    block = PDFBlock()
    result = asyncio.run(block.process(pdf_path))

    assert result["status"] == "success"
    assert result["text"] == fake_ocr or result["text"].startswith(fake_ocr[:50])
    # Either "<engine> + OCR" or "OCR-only" depending on whether the
    # base extractor returned anything at all.
    assert ("+ OCR" in result["engine"]) or (result["engine"] == "OCR-only")


# ── 3. pytesseract ImportError → helper returns None, original stands ────


def test_ocr_fallback_returns_none_when_pytesseract_missing(tmp_path, monkeypatch):
    from app.blocks.pdf import _try_ocr_fallback

    pdf_path = str(tmp_path / "scan.pdf")
    _make_scanned_pdf(pdf_path, pages=1)

    # Force `import pytesseract` to fail inside the helper.
    real_import = __import__

    def _hostile_import(name, *args, **kwargs):
        if name == "pytesseract":
            raise ImportError("forced: pytesseract unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _hostile_import)

    out = _try_ocr_fallback(pdf_path, original_text="")
    assert out is None


def test_pytesseract_missing_keeps_original_extraction(tmp_path, monkeypatch):
    from app.blocks.pdf import PDFBlock

    pdf_path = str(tmp_path / "scan.pdf")
    _make_scanned_pdf(pdf_path, pages=1)

    real_import = __import__

    def _hostile_import(name, *args, **kwargs):
        if name == "pytesseract":
            raise ImportError("forced: pytesseract unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _hostile_import)

    block = PDFBlock()
    result = asyncio.run(block.process(pdf_path))
    # We still get a successful response — engine is the base extractor,
    # not OCR — because the helper failed cleanly and we kept the original.
    assert result["status"] == "success"
    assert "OCR" not in result["engine"], f"engine={result['engine']!r}"


# ── 4. 60-second time budget is respected ─────────────────────────────────


def test_ocr_fallback_respects_time_budget(tmp_path, monkeypatch):
    """Force perf_counter to advance past the budget after the first page —
    the helper must stop iterating instead of OCR'ing every page of a
    long scan."""
    from app.blocks.pdf import _try_ocr_fallback

    pdf_path = str(tmp_path / "scan.pdf")
    _make_scanned_pdf(pdf_path, pages=10)

    pages_processed: List[int] = []

    # Mock pytesseract to (a) record which pages we hit and (b) return
    # text — so the helper would otherwise happily process all 10 pages.
    class _StubPytesseract:
        @staticmethod
        def image_to_string(img, timeout=10):
            pages_processed.append(len(pages_processed))
            return "stub OCR text " * 20

    sys.modules["pytesseract"] = _StubPytesseract  # type: ignore[assignment]

    # Mock time.perf_counter inside the helper: first call seeds `started`,
    # second call (page 0 budget check) is fine, third call jumps past 60s.
    counter = {"n": 0}

    def _fake_perf_counter():
        counter["n"] += 1
        if counter["n"] >= 3:
            return 1000.0  # well past the 60s budget
        return 0.0

    import time as _time

    monkeypatch.setattr(_time, "perf_counter", _fake_perf_counter)

    try:
        out = _try_ocr_fallback(pdf_path, original_text="", time_budget_s=60.0)
    finally:
        sys.modules.pop("pytesseract", None)

    # Helper stopped early — at most one page processed before the budget hit.
    assert len(pages_processed) <= 1, f"processed={len(pages_processed)} pages, expected <= 1"
    # And the helper still returned something usable (or None if no page
    # text accumulated before the budget kicked in) — both shapes are
    # valid; what we're asserting is that we DIDN'T blow past the budget.
    assert out is None or isinstance(out, str)


# ── 5. Helper boundary: max_pages cap ──────────────────────────────────────


def test_ocr_fallback_respects_max_pages(tmp_path, monkeypatch):
    """Cap at 30 pages — feed it 35 and assert we never OCR'd page 31+."""
    from app.blocks.pdf import _try_ocr_fallback

    pdf_path = str(tmp_path / "long_scan.pdf")
    _make_scanned_pdf(pdf_path, pages=35)

    pages_processed: List[int] = []

    class _StubPytesseract:
        @staticmethod
        def image_to_string(img, timeout=10):
            pages_processed.append(len(pages_processed))
            return "x" * 50

    sys.modules["pytesseract"] = _StubPytesseract  # type: ignore[assignment]
    try:
        _try_ocr_fallback(pdf_path, original_text="", max_pages=30, time_budget_s=600)
    finally:
        sys.modules.pop("pytesseract", None)

    assert len(pages_processed) == 30, f"processed {len(pages_processed)}, expected 30"
