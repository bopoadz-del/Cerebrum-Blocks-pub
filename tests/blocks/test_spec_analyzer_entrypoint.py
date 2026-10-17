"""spec_analyzer: the ADVERTISED entry point, against a real PDF.

tests/blocks/test_spec_analyzer_wave1.py constructs ``SpecAnalyzerBlock()``
and then calls the private helper ``_extract_grades`` on a string.
``process()`` -- the method the registry advertises and the only one a caller
ever reaches -- was never invoked, so nothing tested that the block opens a
file, honours ``max_pages``, resolves what it extracted against the grade and
standards tables, or refuses a request it cannot serve.

The fixture is a real artifact: a PDF written to disk with PyMuPDF and reopened
from disk by the block's own ``_extract_text``. Assertions are on the grades,
standards and clauses that had to come out of that file's text layer.
"""
from __future__ import annotations

import fitz
import pytest

from app.blocks.spec_analyzer import SpecAnalyzerBlock

SPEC_LINES = [
    "SECTION 03300 - CONCRETE FORMWORK AND ACCESSORIES",
    "",
    "Part 2 - Products",
    "",
    "Concrete shall be Grade C30/37 in accordance with BS EN 1992-1-1.",
    "Reinforcing steel shall be deformed bars to ASTM A615-22.",
    "All structural concrete shall conform to ACI 318.",
    "Test certificate shall be provided for every delivered batch.",
]

PAGE_TWO_LINES = [
    "Structural steel shall comply with ASTM A992 for wide-flange shapes.",
]


def _write_spec_pdf(path, pages):
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page()
        y = 72
        for line in lines:
            if line:
                page.insert_text((72, y), line, fontsize=10)
            y += 16
    doc.save(str(path))
    doc.close()
    return path


def _grades(result):
    return {(g["type"], g["value"]) for g in result["grade_requirements"]}


async def test_process_reads_a_real_spec_pdf_from_disk(tmp_path):
    """One PDF in, the citations that are actually printed on it out."""
    pdf = _write_spec_pdf(tmp_path / "spec.pdf", [SPEC_LINES])

    result = await SpecAnalyzerBlock().process({"file_path": str(pdf)})

    assert result["status"] == "success"
    assert result["page_count"] == 1

    grades = _grades(result)
    assert ("astm_standard", "A615-22") in grades
    assert ("aci_standard", "318") in grades
    assert ("bs_en_standard", "1992-1") in grades
    assert ("grade", "C30") in grades

    # The section heading the file opens with.
    assert result["sections_found"] >= 1
    assert any("CONCRETE FORMWORK AND ACCESSORIES" in s for s in result["sections"])

    # The obligation clauses, with the sentence each was found in.
    flags = {f["flag_type"] for f in result["compliance_flags"]}
    assert "conformance" in flags
    assert "test_certificate" in flags
    conformance = next(
        f for f in result["compliance_flags"] if f["flag_type"] == "conformance"
    )
    assert "ACI 318" in conformance["context"]


async def test_process_resolves_what_it_extracted_against_the_reference_tables(tmp_path):
    """An extracted code is not left as a bare string: C30 resolves to its
    characteristic strength, ASTM A615 to what the standard covers."""
    pdf = _write_spec_pdf(tmp_path / "spec.pdf", [SPEC_LINES])

    result = await SpecAnalyzerBlock().process({"file_path": str(pdf)})

    c30 = next(
        g for g in result["grade_requirements"]
        if g["type"] == "grade" and g["value"] == "C30"
    )
    assert c30["resolved"]["fck_mpa"] == 30
    assert c30["resolved"]["kind"] == "concrete"
    assert c30["resolved"]["system"] == "EN"

    by_value = {s["value"]: s for s in result["standards_referenced"]}
    assert by_value["A615-22"]["resolved"]["reference"] == "ASTM A615"
    assert by_value["A615-22"]["resolved"]["category"] == "rebar"
    assert (
        by_value["318"]["resolved"]["covers"]
        == "Building code requirements for structural concrete"
    )
    # Deduplicated on (type, value).
    keys = [(s["type"], s["value"]) for s in result["standards_referenced"]]
    assert len(keys) == len(set(keys))


async def test_process_honours_max_pages_instead_of_reading_the_whole_file(tmp_path):
    """The cap is real: with max_pages=1 the page-2 standard is absent, and
    without it the same file yields it."""
    pdf = _write_spec_pdf(tmp_path / "two_page.pdf", [SPEC_LINES, PAGE_TWO_LINES])
    block = SpecAnalyzerBlock()

    capped = await block.process({"file_path": str(pdf)}, {"max_pages": 1})
    full = await block.process({"file_path": str(pdf)})

    assert capped["page_count"] == 1
    assert ("astm_standard", "A992") not in _grades(capped)

    assert full["page_count"] == 2
    assert ("astm_standard", "A992") in _grades(full)


async def test_process_accepts_raw_spec_text_without_a_file(tmp_path):
    result = await SpecAnalyzerBlock().process(
        {"text": "Reinforcement shall be Grade B500B to BS 4449."}
    )

    assert result["status"] == "success"
    assert result["page_count"] == 0
    b500b = next(
        g for g in result["grade_requirements"]
        if g["type"] == "grade" and g["value"] == "B500B"
    )
    assert b500b["resolved"]["fy_mpa"] == 500
    assert b500b["resolved"]["kind"] == "rebar"


async def test_process_refuses_a_request_with_neither_file_nor_text():
    """No input is an error, not an empty spec analysis. An empty
    grade_requirements list reported as success reads to a caller as 'this
    specification names no grades'."""
    result = await SpecAnalyzerBlock().process({})

    assert result["status"] == "error"
    assert result["error"] == "Provide file_path (PDF) or raw spec text as input"
    assert "grade_requirements" not in result


async def test_process_refuses_a_file_path_that_does_not_exist(tmp_path):
    missing = tmp_path / "not_here.pdf"

    result = await SpecAnalyzerBlock().process({"file_path": str(missing)})

    assert result["status"] == "error"
    assert result["error"] == f"File not found: {missing}"


async def test_process_reports_a_pdf_it_cannot_parse_rather_than_an_empty_spec(tmp_path):
    """A file that is not a PDF must surface the extraction failure."""
    fake = tmp_path / "corrupt.pdf"
    fake.write_bytes(b"this is not a PDF at all")

    result = await SpecAnalyzerBlock().process({"file_path": str(fake)})

    assert result["status"] == "error"
    assert result["error"].startswith("PDF extraction failed:")


async def test_execute_carries_the_payload_process_computed(tmp_path):
    pdf = _write_spec_pdf(tmp_path / "spec.pdf", [SPEC_LINES])

    envelope = await SpecAnalyzerBlock().execute({"file_path": str(pdf)})

    assert envelope["block"] == "spec_analyzer"
    assert envelope["status"] == "success"
    payload = envelope["result"]
    assert payload["status"] == "success"
    assert ("astm_standard", "A615-22") in {
        (g["type"], g["value"]) for g in payload["grade_requirements"]
    }


async def test_execute_reports_error_when_process_refused():
    """The base envelope must not launder a refusal into a success."""
    envelope = await SpecAnalyzerBlock().execute({})

    assert envelope["status"] == "error"
    assert envelope["confidence"] == 0.0
    assert envelope["result"]["error"] == (
        "Provide file_path (PDF) or raw spec text as input"
    )
