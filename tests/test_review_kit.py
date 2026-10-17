"""Stage K4: the author pass, and what sign-off is allowed to mean.

The property under test: **sign-off records a person's judgement and cannot
manufacture one.** It refuses while the reviewer's own work is outstanding,
it demands a name, and it writes that name down -- because a trust tier whose
meaning is "somebody vouched for this" records nothing if it cannot say who.
"""

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_kit.py"
_spec = importlib.util.spec_from_file_location("review_kit", _SCRIPT)
review_kit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(review_kit)


def _kit(tmp_path, *, tier="contributor_unverified", status="draft",
         schema_props=None, authored=None, expression="a / b"):
    kit_dir = tmp_path / "dental"
    (kit_dir / "schemas").mkdir(parents=True)
    (kit_dir / "app" / "data").mkdir(parents=True)
    (kit_dir / "evaluation").mkdir(parents=True)

    (kit_dir / "manifest.json").write_text(
        json.dumps({"id": "dental", "status": status, "trust_tier": tier,
                    "_trust_tier_note": "scaffold note"}),
        encoding="utf-8",
    )
    (kit_dir / "schemas" / "patient.json").write_text(
        json.dumps({
            "title": "Patient",
            "description": "Patient",
            "x-provenance": {"kind": "company_policy", "reference": "Ops s2",
                             "extracted_from": "sheet!Entities row 2"},
            "properties": schema_props if schema_props is not None else {},
        }),
        encoding="utf-8",
    )
    (kit_dir / "app" / "data" / "domain_definitions.json").write_text(
        json.dumps({
            "set_id": "dental",
            "definitions": [{
                "id": "util", "name": "util = a / b", "expression": expression,
                "inputs": ["a", "b"] if expression else [],
                "provenance": {"kind": "company_policy", "reference": "Ops s4",
                               "extracted_from": "sheet!Formulas row 2"},
            }],
        }),
        encoding="utf-8",
    )
    (kit_dir / "evaluation" / "golden_questions.json").write_text(
        json.dumps({"authored": authored, "questions": [{"id": "q1"}]}),
        encoding="utf-8",
    )
    return kit_dir


@pytest.fixture(autouse=True)
def _kits_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(review_kit, "KITS_DIR", tmp_path)


# -- the deadlock this had, and must not have again ------------------------


def test_sign_off_does_not_block_on_what_sign_off_itself_sets(tmp_path):
    """The bug that made the stage impossible to complete.

    A reviewer resolves every definition, fills every schema and authors the
    blind evaluation -- and an earlier version still refused, because
    trust_tier was unraised and status was draft. Raising those is what
    signing off does.
    """
    _kit(tmp_path, schema_props={"id": {"type": "string"}}, authored="2026-08-29")

    assert review_kit.blocking_sign_off("dental") == []
    # ...while the full picture still reports both, for the pipeline's benefit.
    full = review_kit.outstanding("dental")
    assert any("trust_tier" in note for note in full)
    assert any("status is draft" in note for note in full)


def test_the_split_comes_from_pipeline_kit_not_a_local_copy():
    """One definition of K4, or a reviewer signs off against the wrong list."""
    findings, set_by_sign_off = review_kit._findings("nothing")
    assert set_by_sign_off == ("trust_tier", "status")


# -- refusals --------------------------------------------------------------


def test_sign_off_refuses_while_a_schema_is_empty(tmp_path, capsys):
    kit_dir = _kit(tmp_path, schema_props={}, authored="2026-08-29")
    code = review_kit.sign_off("dental", kit_dir, "dr-hassan", "2026-08-29")

    assert code == 1
    err = capsys.readouterr().err
    assert "Refusing to sign off" in err
    assert "no properties" in err
    manifest = json.loads((kit_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["trust_tier"] == "contributor_unverified", "tier moved anyway"


def test_sign_off_refuses_while_the_evaluation_is_seeds_only(tmp_path, capsys):
    kit_dir = _kit(tmp_path, schema_props={"id": {}}, authored=None)
    assert review_kit.sign_off("dental", kit_dir, "dr-hassan", "2026-08-29") == 1
    assert "blind evaluation" in capsys.readouterr().err


def test_the_refusal_says_why_it_matters(tmp_path, capsys):
    kit_dir = _kit(tmp_path, schema_props={}, authored=None)
    review_kit.sign_off("dental", kit_dir, "dr-hassan", "2026-08-29")
    err = capsys.readouterr().err
    assert "content they have not finished reviewing" in err


# -- the record ------------------------------------------------------------


def test_a_clean_sign_off_records_who_and_when(tmp_path):
    kit_dir = _kit(tmp_path, schema_props={"id": {}}, authored="2026-08-29")
    assert review_kit.sign_off("dental", kit_dir, "dr-a-hassan", "2026-08-29") == 0

    manifest = json.loads((kit_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["trust_tier"] == "contributor_reviewed"
    assert manifest["status"] == "available"
    assert manifest["review"]["reviewer"] == "dr-a-hassan"
    assert manifest["review"]["reviewed_on"] == "2026-08-29"
    assert manifest["review"]["tier_before"] == "contributor_unverified"


def test_the_scaffold_note_is_removed_once_it_stops_being_true(tmp_path):
    """`_trust_tier_note` says nobody has reviewed this. After sign-off that
    is false, and a stale note is a lie with a citation."""
    kit_dir = _kit(tmp_path, schema_props={"id": {}}, authored="2026-08-29")
    review_kit.sign_off("dental", kit_dir, "dr-hassan", "2026-08-29")
    manifest = json.loads((kit_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "_trust_tier_note" not in manifest


def test_signing_off_without_a_reviewer_is_a_usage_error(tmp_path, monkeypatch, capsys):
    _kit(tmp_path, schema_props={"id": {}}, authored="2026-08-29")
    monkeypatch.setattr("sys.argv", ["review_kit.py", "--kit", "dental", "--sign-off"])
    assert review_kit.main() == 2
    assert "must say who" in capsys.readouterr().err


# -- what the reviewer is shown -------------------------------------------


def test_a_null_expression_definition_is_surfaced_with_its_citation(tmp_path):
    kit_dir = _kit(tmp_path, expression=None)
    pending = review_kit.definitions_needing_review(kit_dir)

    assert len(pending) == 1
    assert pending[0]["why"] == "no expression"
    assert review_kit._cite(pending[0]["provenance"]) == (
        "[company_policy: Ops s4] @ sheet!Formulas row 2"
    )


def test_a_definition_with_an_expression_but_no_inputs_is_also_surfaced(tmp_path):
    kit_dir = _kit(tmp_path, expression="42")
    kit_json = kit_dir / "app" / "data" / "domain_definitions.json"
    data = json.loads(kit_json.read_text(encoding="utf-8"))
    data["definitions"][0]["inputs"] = []
    kit_json.write_text(json.dumps(data), encoding="utf-8")

    pending = review_kit.definitions_needing_review(kit_dir)
    assert pending[0]["why"] == "no inputs named"


def test_the_report_shows_the_sheet_the_kit_came_from(tmp_path, capsys):
    kit_dir = _kit(tmp_path, schema_props={"id": {}}, authored="2026-08-29")
    manifest_path = kit_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["_intake"] = {"sheet": "dental.xlsx", "sheet_sha256": "b" * 64,
                           "contributor_id": "dr-a-hassan"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    review_kit.report("dental", kit_dir)
    out = capsys.readouterr().out
    assert "dental.xlsx" in out
    assert "bbbbbbbbbbbb" in out
    assert "dr-a-hassan" in out


def test_a_kit_with_nothing_outstanding_says_so(tmp_path, capsys):
    kit_dir = _kit(tmp_path, tier="contributor_reviewed", status="available",
                   schema_props={"id": {}}, authored="2026-08-29")
    assert review_kit.report("dental", kit_dir) == []
    assert "Nothing outstanding" in capsys.readouterr().out
