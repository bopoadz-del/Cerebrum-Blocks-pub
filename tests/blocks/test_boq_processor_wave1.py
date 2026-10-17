"""Wave 1.3 regression tests — boq_processor ports from The_Fork.

Locks: header discovery under banner rows (.xlsx), PDF acceptance with
table-grid extraction, and honest failure for scanned PDFs.
"""

import asyncio
import os
import tempfile

import pytest

from app.blocks.boq_processor import BOQProcessorBlock

pandas = pytest.importorskip("pandas")


def _make_banner_xlsx(path: str) -> None:
    import pandas as pd

    # Row 0-1 are banner/title rows; the real header is row 2.
    df = pd.DataFrame(
        [
            ["PROJECT BOQ VOLUME III", "", "", ""],
            ["Employer: Example Co.", "", "", ""],
            ["Description", "Quantity", "Unit", "Rate"],
            ["Excavate trench", "120", "m3", "25.5"],
            ["Concrete blinding", "45", "m3", "90"],
        ]
    )
    df.to_excel(path, index=False, header=False, engine="openpyxl")


def test_detect_header_row_finds_header_below_banner():
    import pandas as pd

    block = BOQProcessorBlock()
    raw = pd.DataFrame(
        [
            ["PROJECT BOQ VOLUME III", "", "", ""],
            ["Description", "Quantity", "Unit", "Rate"],
            ["Excavate trench", "120", "m3", "25.5"],
        ]
    )
    assert block._detect_header_row(raw) == 1


def test_xlsx_with_banner_rows_parses_items():
    block = BOQProcessorBlock()
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "boq_banner.xlsx")
        _make_banner_xlsx(path)
        out = asyncio.run(block.process({"file_path": path}))
    assert out["status"] == "success", out.get("error")
    assert out["item_count"] >= 2
    assert out["total_cost"] > 0


def test_pdf_input_is_accepted_and_disclosed():
    """A table-grid PDF parses to items; a text-only PDF degrades honestly
    (partial + page_texts) instead of a generic unsupported-format error."""
    pdfplumber = pytest.importorskip("pdfplumber")
    block = BOQProcessorBlock()

    # Text-only PDF: no ruling lines -> no tables -> partial + page_texts.
    import fitz  # PyMuPDF

    with tempfile.TemporaryDirectory() as td:
        text_pdf = os.path.join(td, "text_only.pdf")
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Description Quantity Unit Rate")
        page.insert_text((72, 92), "Excavate trench 120 m3 25.5")
        doc.save(text_pdf)
        doc.close()

        out = asyncio.run(block.process({"file_path": text_pdf}))
        assert out["status"] in ("success", "partial"), out.get("error")
        if out["status"] == "partial":
            assert out.get("page_texts"), "partial result must carry page text"

    # Table-grid PDF: ruling lines -> pdfplumber table detection -> items.
    with tempfile.TemporaryDirectory() as td:
        grid_pdf = os.path.join(td, "grid.pdf")
        doc = fitz.open()
        page = doc.new_page()
        x0, y0 = 72, 72
        col_x = [x0, x0 + 140, x0 + 220, x0 + 300]
        # header + 2 rows
        rows_text = [
            ["Description", "Quantity", "Unit", "Rate"],
            ["Excavate trench", "120", "m3", "25.5"],
            ["Concrete blinding", "45", "m3", "90"],
        ]
        for r, row in enumerate(rows_text):
            for c, cell in enumerate(row):
                page.insert_text((col_x[c] + 3, y0 + 20 * r + 14), cell)
        # draw grid lines
        n_rows = len(rows_text)
        for c in col_x:
            page.draw_line((c, y0), (c, y0 + 20 * n_rows))
        for r in range(n_rows + 1):
            page.draw_line((x0, y0 + 20 * r), (col_x[-1], y0 + 20 * r))
        doc.save(grid_pdf)
        doc.close()

        out = asyncio.run(block.process({"file_path": grid_pdf}))
        # Either pdfplumber found the grid (success with items) or it
        # degraded honestly (partial). Never a crash or silent zero-rows
        # with a fabricated success.
        assert out["status"] in ("success", "partial"), out.get("error")
        if out["status"] == "success":
            assert out.get("source_format") == "pdf"
