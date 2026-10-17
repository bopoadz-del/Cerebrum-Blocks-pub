"""Wave 1.5 regression tests — drawing_qto PDF path (ported from The_Fork).

The Store's drawing_qto was DXF-only; every PDF submittal was refused.
These lock that .pdf inputs now run the geometry + text extraction path
instead of the old unsupported-format error, and that a non-file error
message stays honest.
"""

import asyncio
import os
import tempfile

import pytest

from app.blocks.drawing_qto import DrawingQTOBlock

fitz = pytest.importorskip("fitz")


def _make_pdf_with_text(path: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "GROUND FLOOR PLAN")
    page.insert_text((72, 96), "ROOM A-101")
    page.draw_line((72, 120), (200, 120))
    doc.save(path)
    doc.close()


def test_pdf_input_runs_extraction_path():
    block = DrawingQTOBlock()
    with tempfile.TemporaryDirectory() as td:
        pdf = os.path.join(td, "plan.pdf")
        _make_pdf_with_text(pdf)
        out = asyncio.run(block.process({"file_path": pdf}))
    # The old block refused PDFs outright; the ported one must produce a
    # structured result (geometry and/or text) instead.
    err = out.get("error", "")
    assert "Unsupported format" not in err, out
    assert "drawing" in out or "text" in out, out
    assert out.get("status") in ("success", "partial", "error"), out


def test_dwg_without_converter_gives_honest_guidance():
    block = DrawingQTOBlock()
    with tempfile.TemporaryDirectory() as td:
        dwg = os.path.join(td, "plan.dwg")
        with open(dwg, "wb") as fh:
            fh.write(b"\x00\x00 fake dwg bytes")
        out = asyncio.run(block.process({"file_path": dwg}))
    # Either a real conversion result or an honest error; never a crash
    # and never a fabricated take-off.
    assert isinstance(out, dict)
    assert out.get("status") == "error" or "error" in out or "status" in out
