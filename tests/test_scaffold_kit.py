"""Stage K3: a sourced intake in, a kit directory out.

The property under test: **the scaffold emits what the sheet said and
nothing else.** Every place it could be helpful by filling a gap -- an
expression, a schema property, a trust tier, an install-ready status -- it
leaves the gap visible instead, because a generated kit that looks finished
is the one nobody goes back to finish.
"""

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scaffold_kit.py"
_spec = importlib.util.spec_from_file_location("scaffold_kit", _SCRIPT)
scaffold_kit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scaffold_kit)


def _item(text, **kw):
    base = {
        "text": text,
        "section": kw.pop("section", "formulas"),
        "location": kw.pop("location", "sheet.xlsx!Formulas row 2"),
        "source": kw.pop("source", "company_policy"),
        "source_ref": kw.pop("source_ref", "Ops manual s4"),
        "contributor_id": kw.pop("contributor_id", "dr-hassan"),
        "confidence": kw.pop("confidence", None),
    }
    base.update(kw)
    return base


# -- parsing a definition --------------------------------------------------


@pytest.mark.parametrize(
    "text,expected_id,expected_expr",
    [
        ("chair utilisation = booked / available", "chair_utilisation", "booked / available"),
        ("Gross Margin = (rev - cogs) / rev", "gross_margin", "(rev - cogs) / rev"),
        ("recall rate=a/b", "recall_rate", "a/b"),
    ],
)
def test_an_assignment_is_split_mechanically(text, expected_id, expected_expr):
    assert scaffold_kit.parse_definition(text) == (expected_id, expected_expr)


@pytest.mark.parametrize(
    "text",
    [
        "patients should be recalled regularly",
        "utilisation == target",
        "= orphaned",
        "no equals sign here at all",
    ],
)
def test_anything_not_an_assignment_yields_no_expression(text):
    """Guessing would produce arithmetic nobody wrote, carrying a real
    provenance record -- the worst combination available."""
    assert scaffold_kit.parse_definition(text) == (None, None)


def test_inputs_are_identifiers_not_operators():
    assert scaffold_kit.infer_inputs("(revenue - cogs) / revenue") == ["revenue", "cogs"]
    assert scaffold_kit.infer_inputs("max(a, b) + c") == ["a", "b", "c"]


# -- the overlay -----------------------------------------------------------


def test_provenance_is_carried_through_unchanged():
    overlay, _notes = scaffold_kit.build_definitions(
        "dental",
        [_item("util = a / b", source="regulator", source_ref="HKIA GN16", confidence=0.9)],
    )
    prov = overlay["definitions"][0]["provenance"]
    assert prov["kind"] == "regulator"
    assert prov["reference"] == "HKIA GN16"
    assert prov["contributor_id"] == "dr-hassan"
    assert prov["confidence"] == 0.9
    assert prov["extracted_from"] == "sheet.xlsx!Formulas row 2"


def test_a_missing_confidence_stays_missing():
    overlay, _ = scaffold_kit.build_definitions("dental", [_item("util = a / b")])
    assert overlay["definitions"][0]["provenance"]["confidence"] is None


def test_no_definition_ever_declares_an_override():
    """Replacing a base definition is an authored act with a stated reason.

    A scaffold cannot supply one, so it must never emit the key -- the
    precedence resolver would refuse it, and a scaffold that produces
    unresolvable output is a scaffold nobody can use.
    """
    overlay, _ = scaffold_kit.build_definitions(
        "dental",
        [_item("gross_margin = (r - c) / r"), _item("quick_ratio = a / l")],
    )
    assert all("overrides" not in d for d in overlay["definitions"])
    assert all(d["tier"] == "domain-extension" for d in overlay["definitions"])


def test_a_prose_item_is_emitted_with_a_null_expression_and_flagged():
    overlay, notes = scaffold_kit.build_definitions(
        "dental", [_item("patients should be recalled regularly")]
    )
    entry = overlay["definitions"][0]
    assert entry["expression"] is None
    assert entry["inputs"] == []
    assert entry["provenance"]["reference"] == "Ops manual s4"
    assert len(notes) == 1 and "null expression" in notes[0]


def test_duplicate_ids_are_suffixed_and_both_reported():
    """Silently dropping the second would lose a sourced statement."""
    overlay, notes = scaffold_kit.build_definitions(
        "dental",
        [
            _item("util = a / b", location="row 2"),
            _item("util = c / d", location="row 9"),
        ],
    )
    ids = [d["id"] for d in overlay["definitions"]]
    assert ids == ["util", "util_2"]
    assert any("already defined by row 2" in n for n in notes)


def test_the_overlay_targets_the_path_grounding_reads():
    """K1 -> K3 -> K2 closes only if this filename matches.

    formula_definitions._OVERLAY_RELATIVE is app/data/domain_definitions.json;
    a scaffold writing anywhere else produces a kit whose formulas are never
    grounded and whose answers are all flagged model_generated.
    """
    from app.core import formula_definitions

    assert formula_definitions._OVERLAY_RELATIVE.as_posix() == (
        "app/data/domain_definitions.json"
    )


# -- what it refuses to decide ---------------------------------------------


def test_a_scaffolded_kit_is_not_installable():
    """status=available would put it on the shelf claiming a completeness
    nobody checked -- the automotive failure with the labels swapped."""
    assert scaffold_kit.SCAFFOLD_STATUS == "draft"


def test_a_scaffolded_kit_is_not_vouched_for():
    """And the tier it carries must be one the Factory gate rejects."""
    assert scaffold_kit.SCAFFOLD_TRUST_TIER == "contributor_unverified"
    # Mirrors ACCEPTED_TRUST_TIERS in <private-repo>'s compliance_gate.
    assert scaffold_kit.SCAFFOLD_TRUST_TIER not in ("platform", "contributor_reviewed")


def test_entity_schemas_invent_no_properties():
    _name, schema = scaffold_kit.build_entity_schema(
        _item("Patient", section="entities"), "dental"
    )
    assert schema["properties"] == {}, "an empty schema is honestly empty"
    assert schema["description"] == "Patient"
    assert schema["x-provenance"]["reference"] == "Ops manual s4"


def test_the_source_manifest_records_only_stated_sources():
    manifest = scaffold_kit.build_source_manifest(
        "dental",
        [
            _item("a = 1", source="regulator", source_ref="GN16"),
            _item("b = 2", source="regulator", source_ref="GN16"),
            _item("Patient", section="entities", source_ref="Ops manual s2"),
        ],
    )
    families = manifest["source_families"]
    assert len(families) == 2, "identical (source, reference) pairs collapse to one"
    gn16 = next(f for f in families if f["reference"] == "GN16")
    assert gn16["item_count"] == 2
    assert gn16["source_class"] == "regulator"


def test_the_prompt_cites_every_line_it_carries():
    text = scaffold_kit.render_prompt(
        "dental",
        [_item("recall = preventive review", section="vocabulary")],
        [_item("never quote without a plan", section="refusal_traps")],
    )
    assert "recall = preventive review" in text
    assert "never quote without a plan" in text
    assert text.count("[company_policy: Ops manual s4]") == 2
    assert "traceable to a sheet entry" in text


# -- end to end ------------------------------------------------------------


def _intake(tmp_path, sections, kit="dental"):
    path = tmp_path / "intake.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kit": kit,
                "intake": {"sheet": "dental.xlsx", "sheet_sha256": "a" * 64,
                           "contributor_id": "dr-hassan"},
                "sections": sections,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_a_full_scaffold_lands_every_artifact(tmp_path, monkeypatch, capsys):
    intake = _intake(
        tmp_path,
        {
            "formulas": [_item("util = booked / available")],
            "entities": [_item("Patient", section="entities")],
            "vocabulary": [_item("recall = review", section="vocabulary")],
            "refusal_traps": [_item("never guess a price", section="refusal_traps")],
            "workflows": [],
            "precedence": [],
        },
    )
    out = tmp_path / "kit"
    monkeypatch.setattr(
        "sys.argv",
        ["scaffold_kit.py", "--intake", str(intake), "--out", str(out)],
    )
    code = scaffold_kit.main()

    assert code == 0, capsys.readouterr().out
    assert (out / "manifest.json").is_file()
    assert (out / "source_manifest.json").is_file()
    assert (out / "app" / "data" / "domain_definitions.json").is_file()
    assert (out / "schemas" / "patient.json").is_file()
    assert (out / "prompts" / "dental_expert.txt").is_file()

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "dental"
    assert manifest["status"] == "draft"
    assert manifest["trust_tier"] == "contributor_unverified"
    assert manifest["data"] == ["app/data/domain_definitions.json"]
    assert manifest["_intake"]["sheet_sha256"] == "a" * 64
    assert "{{" not in json.dumps(manifest), "template placeholders left unsubstituted"


def test_an_intake_that_encoded_nothing_scaffolds_nothing(tmp_path, monkeypatch):
    """Every item was dropped by K1's gate. A kit built from that would be an
    empty shell wearing a domain's name."""
    intake = _intake(tmp_path, {s: [] for s in ("formulas", "entities")})
    out = tmp_path / "kit"
    monkeypatch.setattr(
        "sys.argv", ["scaffold_kit.py", "--intake", str(intake), "--out", str(out)]
    )
    assert scaffold_kit.main() == 2
    assert not out.exists()


def test_it_refuses_to_overwrite_an_existing_kit(tmp_path, monkeypatch, capsys):
    intake = _intake(tmp_path, {"formulas": [_item("util = a / b")]})
    out = tmp_path / "kit"
    out.mkdir()
    (out / "manifest.json").write_text('{"authored": true}', encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv", ["scaffold_kit.py", "--intake", str(intake), "--out", str(out)]
    )
    assert scaffold_kit.main() == 2
    assert "already exists" in capsys.readouterr().err
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8")) == {
        "authored": True
    }


def test_needing_the_author_is_a_non_zero_exit(tmp_path, monkeypatch):
    """So a pipeline step cannot treat 'scaffolded' as 'ready'."""
    intake = _intake(tmp_path, {"formulas": [_item("recall patients regularly")]})
    out = tmp_path / "kit"
    monkeypatch.setattr(
        "sys.argv", ["scaffold_kit.py", "--intake", str(intake), "--out", str(out)]
    )
    assert scaffold_kit.main() == 1
