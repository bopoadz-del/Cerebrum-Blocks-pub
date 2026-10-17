"""Tests for the neutral PDF export sub-kit."""

import pytest

from block_store.kits.universal_kernel.wave3.pdf_export import (
    PDFBuilder,
    PDFConfigurationError,
)


def test_pdf_builder_to_bytes():
    pytest.importorskip("fpdf")
    builder = PDFBuilder(title="Report", author="Test")
    builder.add_heading("Summary").add_paragraph("Hello world")
    raw = builder.to_bytes()
    assert raw.startswith(b"%PDF")


def test_pdf_builder_add_table():
    pytest.importorskip("fpdf")
    builder = PDFBuilder(title="Table")
    builder.add_table(["id", "name"], [[1, "alice"], [2, "bob"]])
    raw = builder.to_bytes()
    assert raw.startswith(b"%PDF")


def test_pdf_missing_dependency_produces_text_fallback():
    """Simulate missing fpdf by monkeypatching import."""
    import sys

    real_fpdf = sys.modules.get("fpdf")
    sys.modules["fpdf"] = None  # type: ignore[assignment]
    try:
        # The module-level import already happened; instantiate a fresh builder
        # that imports inside to_bytes().
        builder = PDFBuilder(title="Fallback")
        builder.add_paragraph("hello")
        raw = builder.to_bytes()
        text = raw.decode("utf-8")
        assert "Fallback" in text
        assert "honesty=fallback_text_pdf" in text
    finally:
        if real_fpdf is not None:
            sys.modules["fpdf"] = real_fpdf
        else:
            sys.modules.pop("fpdf", None)
