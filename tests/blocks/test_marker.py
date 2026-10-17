"""Tests for Marker PDF Block.

The block reads the PDF text layer with pypdfium2 (PyMuPDF fallback). The
sample PDFs are written byte for byte here, so the contract is proven on real
files that both engines parse, with no fixture on disk.
"""

import ast
import json
import os
import sys
from pathlib import Path

import pytest

from app.blocks import MarkerBlock
from app.blocks import marker as marker_mod
from app.blocks.marker import _try_marker

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "block_registry" / "marker" / "block.json"


def _pdf(pages):
    """A minimal valid PDF. Each item is the page's text, or None for an
    image-only page (a 1x1 inline image and no text: what a scan looks like)."""
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>",
            3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    kids = []
    for i, text in enumerate(pages):
        page_no, content_no = 4 + 2 * i, 5 + 2 * i
        kids.append(f"{page_no} 0 R".encode())
        if text is None:
            stream = b"q 100 0 0 100 50 50 cm BI /W 1 /H 1 /CS /G /BPC 8 ID \x80 EI Q"
        else:
            stream = b"BT /F1 12 Tf 72 720 Td (" + text.encode("latin-1") + b") Tj ET"
        objs[page_no] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents "
            + f"{content_no} 0 R".encode() + b" >>"
        )
        objs[content_no] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
    objs[2] = b"<< /Type /Pages /Kids [" + b" ".join(kids) + b"] /Count " + str(len(pages)).encode() + b" >>"
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for n in sorted(objs):
        offsets[n] = len(out)
        out += f"{n} 0 obj\n".encode() + objs[n] + b"\nendobj\n"
    xref = len(out)
    size = max(objs) + 1
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    for n in range(1, size):
        out += f"{offsets[n]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


@pytest.fixture
def marker_block():
    return MarkerBlock()


@pytest.fixture
def write_pdf(tmp_path):
    def _write(pages, name="sample.pdf"):
        path = tmp_path / name
        path.write_bytes(_pdf(pages))
        return str(path)
    return _write


@pytest.fixture(params=["pypdfium2", "pymupdf"])
def engine(request, monkeypatch):
    """Run the test once per engine: the other one is made unavailable."""
    other = {"pypdfium2": "fitz", "pymupdf": "pypdfium2"}[request.param]
    monkeypatch.setitem(sys.modules, other, None)
    return request.param


# --- declared contract -------------------------------------------------------


def test_manifest_contract_is_unchanged():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert m["id"] == "marker"
    assert [(i["name"], i["type"], i["required"]) for i in m["inputs"]] == [
        ("input", "file", False),
        ("max_chars", "number", False),
    ]
    assert [(o["name"], o["type"]) for o in m["outputs"]] == [("text", "text"), ("pages", "number")]


def test_manifest_says_there_is_no_ocr():
    assert "no OCR" in json.loads(MANIFEST.read_text(encoding="utf-8"))["description"]


def test_block_never_imports_a_pillow_pinning_package():
    """marker-pdf and surya-ocr pin pillow<11; neither may come back."""
    for rel in ("app/blocks/marker.py", "app/blocks/pdf.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        tops = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                tops |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and not node.level:
                tops.add((node.module or "").split(".")[0])
        assert not tops & {"marker", "surya"}, rel
    reqs = (ROOT / "block_registry/marker/requirements.txt").read_text(encoding="utf-8").lower()
    assert "marker-pdf" not in reqs.split("#")[0]
    lines = [l.split("#")[0].strip() for l in reqs.splitlines()]
    assert not any(l.startswith(("marker-pdf", "surya", "pillow")) for l in lines)


@pytest.mark.asyncio
async def test_marker_block_metadata(marker_block):
    assert marker_block.name == "marker"
    assert marker_block.version == "1.0.0"
    assert "pdf" in marker_block.tags
    assert "markdown" in marker_block.tags


# --- behaviour on sample PDFs, per engine ------------------------------------


@pytest.mark.asyncio
async def test_text_pdf_yields_text_and_pages(marker_block, write_pdf, engine):
    path = write_pdf(["Hello Marker page one", "Second page text"])
    result = await marker_block.execute({"file_path": path}, {})
    assert result["status"] == "success"
    out = result["result"]
    assert "Hello Marker page one" in out["text"]
    assert "Second page text" in out["text"]
    assert out["pages"] == 2
    assert out["engine"] == engine
    assert out["pages_without_text"] == []
    assert "warnings" not in out


@pytest.mark.asyncio
async def test_max_chars_truncates(marker_block, write_pdf, engine):
    path = write_pdf(["Hello Marker page one"])
    result = await marker_block.execute({"file_path": path}, {"max_chars": 5})
    assert result["result"]["text"] == "Hello"


@pytest.mark.asyncio
async def test_bytes_input_is_accepted(marker_block, engine):
    result = await marker_block.execute({"file": _pdf(["From bytes"])}, {})
    assert result["status"] == "success"
    assert "From bytes" in result["result"]["text"]


@pytest.mark.asyncio
async def test_image_only_page_is_reported_not_silent(marker_block, write_pdf, engine):
    path = write_pdf(["Typed page", None])
    result = await marker_block.execute({"file_path": path}, {})
    assert result["status"] == "success"
    out = result["result"]
    assert out["pages"] == 2
    assert out["pages_without_text"] == [2]
    assert "does not OCR" in out["warnings"][0]


@pytest.mark.asyncio
async def test_scanned_pdf_is_an_error_naming_the_ocr_gap(marker_block, write_pdf, engine):
    path = write_pdf([None, None])
    result = await marker_block.execute({"file_path": path}, {})
    assert result["status"] == "error"
    assert "does not OCR" in str(result["result"]["error"])


@pytest.mark.asyncio
async def test_unreadable_pdf_is_an_error(marker_block, tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4 not really")
    result = await marker_block.execute({"file_path": str(path)}, {})
    assert result["status"] == "error"
    assert "could not be read" in str(result["result"]["error"])


@pytest.mark.asyncio
async def test_marker_block_file_not_found(marker_block):
    result = await marker_block.execute(
        {"file_path": "/tmp/definitely_not_real.pdf"},
        {},
    )
    assert result["status"] == "error"
    inner = result.get("result", {})
    assert "File not found" in str(inner.get("error", ""))


# --- no engine installed -------------------------------------------------------


def test_try_marker_returns_none_when_no_engine(monkeypatch, write_pdf):
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    monkeypatch.setitem(sys.modules, "fitz", None)
    assert _try_marker(write_pdf(["x"])) is None


@pytest.mark.asyncio
async def test_marker_block_missing_dependency(marker_block, monkeypatch, write_pdf):
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    monkeypatch.setitem(sys.modules, "fitz", None)
    result = await marker_block.execute({"file_path": write_pdf(["x"])}, {})
    assert result["status"] == "error"
    error = str(result["result"]["error"])
    assert "no PDF engine installed" in error
    assert "pypdfium2" in error and "pymupdf" in error


def test_engine_order_is_pypdfium2_then_pymupdf():
    assert [name for name, _ in marker_mod.ENGINES] == ["pypdfium2", "pymupdf"]
