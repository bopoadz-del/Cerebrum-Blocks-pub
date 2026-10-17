"""Tests for the neutral document parsing sub-kit."""

import io

import pytest
from openpyxl import Workbook

from block_store.kits.universal_kernel.wave2.document_parsing import Document, ParseError, parse


def test_parse_text_plain():
    doc = parse(b"hello world", "text/plain", "notes.txt")
    assert doc.text == "hello world"
    assert doc.honesty == "parsed"


def test_parse_csv():
    content = b"name,age\nAlice,30\nBob,25"
    doc = parse(content, "text/csv", "people.csv")
    assert "Alice, 30" in doc.text
    assert doc.metadata["row_count"] == 2


def test_parse_markdown():
    doc = parse(b"# Heading\n\nbody", "text/markdown", "notes.md")
    assert "# Heading" in doc.text


def test_parse_json():
    doc = parse(b'{"a": 1}', "application/json", "data.json")
    assert '"a": 1' in doc.text


def test_parse_xlsx():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(["name", "age"])
    sheet.append(["Alice", 30])
    buf = io.BytesIO()
    workbook.save(buf)
    doc = parse(buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "people.xlsx")
    assert "[Sheet1]" in doc.text
    assert doc.metadata["row_count"] == 1


def test_unsupported_type_raises():
    with pytest.raises(ParseError):
        parse(b"data", "application/unknown", "data.bin")


def test_unsupported_type_fallback():
    doc = parse(b"data", "application/unknown", "data.bin", extract_raw=True)
    assert doc.text == ""
    assert doc.honesty == "fallback"
    assert "error" in doc.metadata


def test_pdf_parsing_when_pypdf_available():
    pytest.importorskip("pypdf")
    # Minimal valid PDF header; pypdf will parse zero pages without error.
    content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\nxref\n0 3\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \ntrailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n123\n%%EOF"
    doc = parse(content, "application/pdf", "empty.pdf")
    assert doc.metadata["type"] == "pdf"
