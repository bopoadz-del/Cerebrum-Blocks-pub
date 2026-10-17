"""Stage K1: an encoding sheet in, a sourced intake out.

The property under test throughout: **the tool refuses rather than guesses.**
An item with no source is dropped and named. A section it cannot map is
reported, not filed under the nearest-looking heading. A confidence nobody
stated stays null. Each of those is a place where being helpful would mean
putting an unattributed assertion into a kit, where nothing downstream could
tell it from a sourced one.
"""

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "intake_kit.py"
_spec = importlib.util.spec_from_file_location("intake_kit", _SCRIPT)
intake_kit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(intake_kit)


def _sheet(tmp_path, payload, name="sheet.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run(tmp_path, payload, **kw):
    sheet = _sheet(tmp_path, payload)
    items, unmapped = intake_kit.read_structured(
        sheet, dict(intake_kit.SECTION_ALIASES), kw.get("contributor", "dr-hassan")
    )
    kept, dropped = intake_kit.apply_source_gate(items)
    return sheet, items, unmapped, kept, dropped


# -- no source, no encode --------------------------------------------------


def test_a_sourced_item_is_encoded(tmp_path):
    _s, _i, _u, kept, dropped = _run(
        tmp_path,
        {
            "Formulas": [
                {
                    "item": "chair utilisation = booked_hours / available_hours",
                    "source": "company_policy",
                    "source_ref": "Clinic ops manual s4.2",
                    "confidence": 0.9,
                }
            ]
        },
    )
    assert dropped == []
    assert len(kept) == 1
    assert kept[0]["section"] == "formulas"
    assert kept[0]["contributor_id"] == "dr-hassan"
    assert kept[0]["confidence"] == 0.9


def test_an_item_with_no_source_is_dropped_and_named(tmp_path):
    """The rule the whole stage exists for."""
    _s, _i, _u, kept, dropped = _run(
        tmp_path,
        {"Formulas": [{"item": "recall rate is usually about 40%"}]},
    )
    assert kept == []
    assert len(dropped) == 1
    assert dropped[0]["reason"] == "no source named"
    assert "recall rate" in dropped[0]["text"]
    assert dropped[0]["location"].endswith("Formulas[1]")


def test_a_source_with_no_reference_is_dropped(tmp_path):
    """Naming a kind is not citing anything.

    'regulator' with no reference is the shape of a claim that sounds sourced
    and cannot be checked -- the most dangerous of the three failures.
    """
    _s, _i, _u, kept, dropped = _run(
        tmp_path,
        {"Formulas": [{"item": "fluoride varnish interval", "source": "regulator"}]},
    )
    assert kept == []
    assert dropped[0]["reason"] == "source named but no reference given"


def test_an_unrecognised_source_kind_is_refused_not_coerced(tmp_path):
    """'internal doc' is not a synonym for 'standard'."""
    _s, _i, _u, kept, dropped = _run(
        tmp_path,
        {
            "Formulas": [
                {
                    "item": "x",
                    "source": "internal doc",
                    "source_ref": "somewhere",
                }
            ]
        },
    )
    assert kept == []
    assert "is not one of" in dropped[0]["reason"]


def test_the_gate_reports_every_drop_not_just_the_first(tmp_path):
    _s, _i, _u, kept, dropped = _run(
        tmp_path,
        {
            "Formulas": [
                {"item": "a"},
                {"item": "b", "source": "regulator"},
                {"item": "c", "source": "made up", "source_ref": "r"},
                {"item": "d", "source": "standard", "source_ref": "ISO 1"},
            ]
        },
    )
    assert len(kept) == 1
    assert len(dropped) == 3, "a contributor fixing one drop at a time learns slowly"


# -- what it will not guess ------------------------------------------------


def test_an_unmapped_section_is_reported_not_filed_under_a_guess(tmp_path):
    """'Billing Codes' resembles nothing in the map. It must not become vocabulary."""
    _s, items, unmapped, kept, _d = _run(
        tmp_path,
        {
            "Billing Codes": [
                {"item": "D0120", "source": "standard", "source_ref": "CDT 2026"}
            ]
        },
    )
    assert items == []
    assert kept == []
    assert any("Billing Codes" in note for note in unmapped)


def test_confidence_is_never_synthesised(tmp_path):
    """A made-up 0.8 survives into the kit looking measured."""
    _s, _i, _u, kept, _d = _run(
        tmp_path,
        {
            "Formulas": [
                {"item": "x", "source": "standard", "source_ref": "ISO 1"},
                {
                    "item": "y",
                    "source": "standard",
                    "source_ref": "ISO 2",
                    "confidence": "",
                },
            ]
        },
    )
    assert [i["confidence"] for i in kept] == [None, None]


def test_a_table_with_an_unrecognised_header_is_not_parsed_positionally():
    """Column order is not a contract anyone wrote down.

    Guessing would assign somebody's `notes` column to `source_ref` and
    manufacture a citation.
    """
    assert intake_kit._header_map(["notes", "owner", "when"]) is None
    assert intake_kit._header_map(["item", "source", "reference"]) == {
        0: "text",
        1: "source",
        2: "source_ref",
    }


def test_a_header_without_an_item_column_is_unrecognised():
    """Metadata with nothing to attach it to is not a table of assertions."""
    assert intake_kit._header_map(["source", "reference", "confidence"]) is None


# -- section mapping -------------------------------------------------------


@pytest.mark.parametrize(
    "heading,expected",
    [
        ("Formulas", "formulas"),
        ("formulas", "formulas"),
        ("3. Formulas", "formulas"),
        ("Section 4 - Workflows", "workflows"),
        ("Glossary", "vocabulary"),
        ("Section 17", "refusal_traps"),
        ("Refusal Traps", "refusal_traps"),
        ("Chair Inventory", None),
    ],
)
def test_headings_map_only_when_they_actually_match(heading, expected):
    assert intake_kit._map_section(heading, intake_kit.SECTION_ALIASES) == expected


# -- the document it writes ------------------------------------------------


def test_the_intake_records_the_sheet_it_came_from(tmp_path):
    sheet, _i, unmapped, kept, dropped = _run(
        tmp_path,
        {
            "Formulas": [
                {"item": "x", "source": "standard", "source_ref": "ISO 1"},
                {"item": "unsourced"},
            ]
        },
    )
    doc = intake_kit.build_intake(
        "dental", sheet, kept, dropped, unmapped, "dr-hassan", "2026-08-27T00:00:00Z"
    )

    assert doc["kit"] == "dental"
    assert doc["intake"]["contributor_id"] == "dr-hassan"
    assert len(doc["intake"]["sheet_sha256"]) == 64, "the sheet is not pinned"
    assert doc["report"]["encoded"] == 1
    assert len(doc["report"]["dropped"]) == 1
    assert set(doc["sections"]) == set(intake_kit.SECTIONS)


def test_dropped_items_are_absent_from_the_sections(tmp_path):
    """The report lists them; the kit content must not contain them."""
    sheet, _i, unmapped, kept, dropped = _run(
        tmp_path, {"Formulas": [{"item": "unsourced claim"}]}
    )
    doc = intake_kit.build_intake(
        "dental", sheet, kept, dropped, unmapped, "dr-hassan", "t"
    )
    encoded_text = json.dumps(doc["sections"])
    assert "unsourced claim" not in encoded_text
    assert "unsourced claim" in json.dumps(doc["report"])


# -- real files ------------------------------------------------------------


def test_a_real_xlsx_round_trips(tmp_path):
    import openpyxl
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Formulas"
    sheet.append(["item", "source", "reference", "confidence"])
    sheet.append(["chair utilisation", "company_policy", "Ops manual s4", 0.8])
    sheet.append(["unsourced guess", "", "", ""])
    extra = book.create_sheet("Chair Inventory")
    extra.append(["item", "source", "reference"])
    extra.append(["chair 1", "contributor", "site visit"])
    path = tmp_path / "dental.xlsx"
    book.save(path)

    items, unmapped = intake_kit.read_xlsx(
        path, dict(intake_kit.SECTION_ALIASES), "dr-hassan"
    )
    kept, dropped = intake_kit.apply_source_gate(items)

    assert [i["text"] for i in kept] == ["chair utilisation"]
    assert kept[0]["location"] == "dental.xlsx!Formulas row 2"
    assert len(dropped) == 1
    assert any("Chair Inventory" in n for n in unmapped)


def test_a_real_docx_attributes_each_table_to_its_own_heading(tmp_path):
    """Two headings, two tables -- and one heading owning two tables.

    Pairing table N with heading N would misfile the third table. This is the
    case that made the first implementation wrong.
    """
    import docx
    document = docx.Document()
    document.add_heading("Formulas", level=1)
    table = document.add_table(rows=2, cols=3)
    for col, value in enumerate(["item", "source", "reference"]):
        table.cell(0, col).text = value
    for col, value in enumerate(["utilisation", "standard", "ISO 1"]):
        table.cell(1, col).text = value

    document.add_heading("Workflows", level=1)
    for label in ("recall workflow", "triage workflow"):
        second = document.add_table(rows=2, cols=3)
        for col, value in enumerate(["item", "source", "reference"]):
            second.cell(0, col).text = value
        for col, value in enumerate([label, "company_policy", "SOP 1"]):
            second.cell(1, col).text = value

    path = tmp_path / "dental.docx"
    document.save(path)

    items, _unmapped = intake_kit.read_docx(
        path, dict(intake_kit.SECTION_ALIASES), "dr-hassan"
    )
    kept, _dropped = intake_kit.apply_source_gate(items)
    by_section = {}
    for item in kept:
        by_section.setdefault(item["section"], []).append(item["text"])

    assert by_section["formulas"] == ["utilisation"]
    assert by_section["workflows"] == ["recall workflow", "triage workflow"]
