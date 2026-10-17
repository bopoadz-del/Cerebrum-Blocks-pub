"""Stage K6: evaluation seeds derived from a kit's own encoding sheet.

The property under test: **a generated eval must never be mistakable for an
authored one.** Seeds derived from the sheet are corpus-sighted by
construction -- they ask the kit about what it was given, so a high score
means nothing was lost, not that the kit is any good. Every field that could
blur that line is pinned here.
"""

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_kit_eval.py"
_spec = importlib.util.spec_from_file_location("build_kit_eval", _SCRIPT)
build_kit_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_kit_eval)


def _item(text, section="formulas", **kw):
    return {
        "text": text,
        "section": section,
        "location": kw.get("location", "sheet.xlsx!S row 2"),
        "source": kw.get("source", "company_policy"),
        "source_ref": kw.get("source_ref", "Ops manual s4"),
        "contributor_id": "dr-hassan",
        "confidence": kw.get("confidence"),
    }


def _intake(**sections):
    base = {s: [] for s in ("formulas", "entities", "workflows", "vocabulary",
                            "precedence", "refusal_traps")}
    base.update(sections)
    return {
        "kit": "dental",
        "intake": {"sheet": "dental.xlsx", "sheet_sha256": "a" * 64},
        "sections": base,
    }


# -- the line between generated and authored -------------------------------


def test_authored_is_null_and_never_a_date():
    """`evals/blind_construction_eval.json` carries `authored: <date>`.

    Writing a date here would claim a human wrote these questions. The whole
    value of the field is that it distinguishes the two.
    """
    doc, _ = build_kit_eval.build_eval(
        _intake(refusal_traps=[_item("never guess a price", "refusal_traps")])
    )
    assert doc["authored"] is None
    assert doc["generated_by"] == "scripts/build_kit_eval.py"


def test_the_method_states_that_the_set_is_corpus_sighted():
    """A reader six months from now must not mistake this for a blind eval."""
    doc, _ = build_kit_eval.build_eval(
        _intake(refusal_traps=[_item("never guess", "refusal_traps")])
    )
    method = doc["method"].lower()
    assert "corpus-sighted" in method
    assert "blind" in method
    assert "not that it is good at the domain" in method


def test_a_generated_set_is_never_publishable_on_its_own():
    """Even a set that hits the target count is still corpus-sighted."""
    traps = [_item(f"never do thing {i}", "refusal_traps") for i in range(12)]
    doc, _ = build_kit_eval.build_eval(_intake(refusal_traps=traps))
    assert doc["coverage"]["total"] >= build_kit_eval.TARGET_QUESTIONS

    reasons = build_kit_eval.assess(doc)
    assert any("no authored blind evaluation" in r for r in reasons)


# -- what is derivable -----------------------------------------------------


def test_a_refusal_trap_becomes_a_question_that_must_be_refused():
    doc, _ = build_kit_eval.build_eval(
        _intake(
            refusal_traps=[
                _item("never quote a price without a treatment plan", "refusal_traps")
            ]
        )
    )
    q = doc["questions"][0]
    assert q["kind"] == "refusal"
    assert q["expected_behaviour"] == "refuse"
    assert "quote" in q["expected_keywords"]
    assert q["provenance"]["source_ref"] == "Ops manual s4"


def test_a_formula_asks_how_it_is_computed_with_its_own_identifiers():
    doc, _ = build_kit_eval.build_eval(
        _intake(formulas=[_item("chair utilisation = booked_hours / available_hours")])
    )
    q = doc["questions"][0]
    assert q["question"] == "How is chair utilisation calculated?"
    assert q["expected_keywords"] == ["booked_hours", "available_hours"]
    assert q["expected_behaviour"] == "answer"


def test_a_formula_with_no_expression_is_skipped_and_named():
    """It cannot supply ground truth, so it must not become a question.

    Asking 'how is <prose> calculated?' with keywords scraped from the prose
    would score on the prose being retrieved, which tests nothing.
    """
    doc, skipped = build_kit_eval.build_eval(
        _intake(formulas=[_item("patients should be recalled regularly",
                                location="row 4")])
    )
    assert doc["questions"] == []
    assert skipped == ["row 4"]


def test_vocabulary_takes_ground_truth_from_the_definition_body():
    doc, _ = build_kit_eval.build_eval(
        _intake(vocabulary=[_item("recall = scheduled preventive review", "vocabulary")])
    )
    q = doc["questions"][0]
    assert "'recall'" in q["question"]
    assert q["expected_keywords"] == ["scheduled", "preventive", "review"]
    assert "recall" not in q["expected_keywords"], "the term itself is not evidence"


def test_every_question_carries_its_citation():
    doc, _ = build_kit_eval.build_eval(
        _intake(
            formulas=[_item("a = b / c", source="regulator", source_ref="GN16")],
            refusal_traps=[_item("never x", "refusal_traps", source_ref="SOP 2")],
            vocabulary=[_item("t = meaning here", "vocabulary", source_ref="Gloss 1")],
        )
    )
    refs = sorted(q["provenance"]["source_ref"] for q in doc["questions"])
    assert refs == ["GN16", "Gloss 1", "SOP 2"]
    assert all(q["provenance"]["extracted_from"] for q in doc["questions"])


# -- keywords --------------------------------------------------------------


def test_keywords_drop_stopwords_dedupe_and_cap():
    assert build_kit_eval.keywords("the price and the treatment plan") == [
        "price",
        "treatment",
        "plan",
    ]
    assert build_kit_eval.keywords("a b c") == [], "sub-3-char tokens carry no signal"
    assert len(build_kit_eval.keywords(" ".join(f"word{i}" for i in range(20)))) == 4


# -- the verdict -----------------------------------------------------------


def test_below_target_is_reported_as_the_sheets_state_not_a_tool_failure():
    doc, _ = build_kit_eval.build_eval(
        _intake(refusal_traps=[_item("never x", "refusal_traps")])
    )
    reasons = build_kit_eval.assess(doc)
    assert any("target is 10" in r for r in reasons)
    assert any("the sheet did not state enough" in r for r in reasons)


def test_no_refusal_traps_is_called_out_specifically():
    """A kit nobody told what to decline has nothing testing that it does."""
    doc, _ = build_kit_eval.build_eval(_intake(formulas=[_item("a = b / c")]))
    assert any("no refusal traps" in r for r in build_kit_eval.assess(doc))


def test_an_intake_with_nothing_derivable_exits_two(tmp_path, monkeypatch, capsys):
    path = tmp_path / "intake.json"
    path.write_text(json.dumps(_intake()), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["build_kit_eval.py", "--intake", str(path)])

    assert build_kit_eval.main() == 2
    assert "thin sheet yields a thin eval" in capsys.readouterr().err


def test_check_reports_without_writing(tmp_path, monkeypatch):
    path = tmp_path / "intake.json"
    path.write_text(
        json.dumps(_intake(refusal_traps=[_item("never x", "refusal_traps")])),
        encoding="utf-8",
    )
    out = tmp_path / "eval.json"
    monkeypatch.setattr(
        "sys.argv",
        ["build_kit_eval.py", "--intake", str(path), "--out", str(out), "--check"],
    )
    assert build_kit_eval.main() == 1
    assert not out.exists(), "--check wrote a file"


def test_writing_records_the_sheet_it_derived_from(tmp_path, monkeypatch):
    path = tmp_path / "intake.json"
    path.write_text(
        json.dumps(_intake(refusal_traps=[_item("never x", "refusal_traps")])),
        encoding="utf-8",
    )
    out = tmp_path / "eval.json"
    monkeypatch.setattr(
        "sys.argv", ["build_kit_eval.py", "--intake", str(path), "--out", str(out)]
    )
    build_kit_eval.main()

    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["source_intake"]["sheet_sha256"] == "a" * 64
    assert doc["schema_version"] == build_kit_eval.SCHEMA_VERSION
