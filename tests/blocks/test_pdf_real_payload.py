"""PDFBlock.process — entry-point coverage against a real drawing on disk.

Why this file exists
--------------------
``tests/blocks/test_pdf.py`` drives ``execute`` and asserts only the
UniversalBlock envelope keys (``block``/``request_id``/``status``/``result``/
``confidence``). ``TypedBlock.execute`` supplies every one of those regardless
of what ``process`` returned, so the control-delete in
``scripts/certify_block.py`` (bar 3) gutted ``PDFBlock.process`` to
``{"block": ..., "status": "success"}`` and the suite stayed GREEN.

Every assertion below is on a value ``process`` had to compute from a real
file: text lifted out of the title block of a 485 KB Sample Design Consultant construction
drawing, the page count, the engine that won the parser race, the basename it
derived, and the exact error strings the two rejection paths produce. None of
them survive a gutted ``process``.
"""

from __future__ import annotations

import os
from pathlib import Path

import openpyxl
import pytest

from app.blocks.pdf import PDFBlock


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DRAWING = FIXTURES / "synthetic_tm_detail.pdf"

# Parsing this drawing costs ~5 s, so the happy-path tests share one parse.
_PARSED: dict = {}


async def _drawing_result() -> dict:
    if "value" not in _PARSED:
        _PARSED["value"] = await PDFBlock().process({"file_path": str(DRAWING)}, {})
    return _PARSED["value"]


async def test_process_extracts_the_drawings_title_block_text():
    """Text that only a real parse of this PDF can produce."""
    result = await _drawing_result()

    assert result["status"] == "success"
    text = result["text"]

    # Title block of the Reference Project Phase II infrastructure package.
    assert "EXAMPLE DEVELOPMENT AUTHORITY" in text
    assert "SAMPLE REGION" in text
    assert "Sample Design Consultant" in text
    assert "WGS-84" in text

    # Drawing notes and the cross-reference drawing numbers they cite.
    assert "ALL DIMENSIONS ARE IN METERS" in text
    assert "PK-INF-001-0000-FRM-DWG-TM-200-0015001" in text

    # Legend entries rendered as separate text runs on the sheet.
    assert "PROJECT BOUNDARY" in text
    assert "BUS STOP" in text

    # Match-line callouts carry a sheet number the parser must keep intact.
    assert "MATCH LINE : FOR REFERENCE REFER TO SHEET NO : 10" in text

    assert len(text) > 2000, f"only {len(text)} chars extracted from a full sheet"


async def test_process_reports_page_count_engine_and_filename():
    """Structural facts derived from the file, not from the envelope."""
    result = await _drawing_result()

    assert result["pages"] == 1, "the fixture is a single-sheet drawing"
    assert result["filename"] == "synthetic_tm_detail.pdf"
    assert result["file_path"] == str(DRAWING)
    # Whichever parser won the race, the block must name it.
    assert result["engine"] in {"pdfplumber", "pypdf", "PyMuPDF"}


async def test_process_accepts_raw_bytes_and_extracts_the_same_text():
    """The bytes branch of _get_pdf_path spools to a temp file and parses it."""
    payload = DRAWING.read_bytes()
    result = await PDFBlock().process(payload, {})
    reference = await _drawing_result()

    assert result["status"] == "success"
    assert result["text"] == reference["text"]
    assert result["pages"] == 1
    # It parsed a temp spool, not the fixture path.
    assert result["file_path"] != str(DRAWING)
    assert result["file_path"].endswith(".pdf")
    assert os.path.exists(result["file_path"])


async def test_process_reads_a_real_workbook_through_the_openpyxl_branch(tmp_path):
    """.xlsx input is a real parse too: sheet headers and cell values come back."""
    book = tmp_path / "boq_extract.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Bill 2 - Concrete"
    ws.append(["Item", "Description", "Qty", "Unit"])
    ws.append(["2.01", "Concrete C30 to foundations", 1250.5, "m3"])
    ws.append(["2.02", "Rebar mesh A393", 87, "t"])
    wb.create_sheet("Preliminaries")
    wb.save(book)

    result = await PDFBlock().process({"file_path": str(book)}, {})

    assert result["status"] == "success"
    assert result["engine"] == "openpyxl"
    assert result["filename"] == "boq_extract.xlsx"
    assert result["pages"] == 2, "one page per worksheet"

    text = result["text"]
    assert "=== Sheet: Bill 2 - Concrete ===" in text
    assert "=== Sheet: Preliminaries ===" in text
    assert "Concrete C30 to foundations" in text
    assert "1250.5" in text
    assert "Rebar mesh A393\t87\tt" in text, "rows are tab-joined"


async def test_missing_file_reports_the_path_it_was_given():
    """The not-found path returns a specific, quotable error."""
    result = await PDFBlock().process({"file_path": "/tmp/no_such_drawing.pdf"}, {})

    assert result["status"] == "error"
    assert result["error"] == "File not found: /tmp/no_such_drawing.pdf"
    assert result["text"] == ""
    assert result["pages"] == 0


async def test_input_without_any_path_is_rejected_by_name():
    """A dict carrying nothing the block can open is a distinct error."""
    result = await PDFBlock().process({"unrelated": "value"}, {})

    assert result["status"] == "error"
    assert result["error"] == "No PDF provided"
    assert result["text"] == ""
    assert result["pages"] == 0
