"""The pipeline runner, and the state it is supposed to stop in.

The property under test: **the pipeline does not complete on its own, and
says so.** K4 is a person. A runner that reported "done" after scaffolding
would be inviting the one outcome the whole design refuses -- a kit on the
shelf whose content nobody vouched for.
"""

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pipeline_kit.py"
_spec = importlib.util.spec_from_file_location("pipeline_kit", _SCRIPT)
pipeline_kit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pipeline_kit)


def _stage(key="K4", title="author pass"):
    return pipeline_kit.Stage(key, title)


# -- the terminal state ----------------------------------------------------


def test_a_fresh_scaffold_blocks_at_the_author_pass(tmp_path, monkeypatch, capsys):
    """Every reason must be a claim only a person can make."""
    kit_dir = tmp_path / "dental"
    (kit_dir / "schemas").mkdir(parents=True)
    (kit_dir / "manifest.json").write_text(
        json.dumps({"id": "dental", "status": "draft",
                    "trust_tier": "contributor_unverified"}),
        encoding="utf-8",
    )
    (kit_dir / "schemas" / "patient.json").write_text(
        json.dumps({"title": "Patient", "properties": {}}), encoding="utf-8"
    )
    (kit_dir / "evaluation").mkdir()
    (kit_dir / "evaluation" / "golden_questions.json").write_text(
        json.dumps({"authored": None, "questions": [{"id": "q1"}]}), encoding="utf-8"
    )
    monkeypatch.setattr(pipeline_kit, "KITS_DIR", tmp_path)

    stage = _stage()
    assert pipeline_kit.check_author_pass("dental", stage) is False
    assert stage.status == pipeline_kit.BLOCKED

    joined = " | ".join(stage.todo)
    assert "trust_tier is contributor_unverified" in joined
    assert "status is draft" in joined
    assert "no properties" in joined
    assert "blind evaluation must be authored" in joined


def test_a_completed_author_pass_clears_k4(tmp_path, monkeypatch):
    kit_dir = tmp_path / "dental"
    (kit_dir / "schemas").mkdir(parents=True)
    (kit_dir / "manifest.json").write_text(
        json.dumps({"id": "dental", "status": "available",
                    "trust_tier": "contributor_reviewed"}),
        encoding="utf-8",
    )
    (kit_dir / "schemas" / "patient.json").write_text(
        json.dumps({"title": "Patient", "properties": {"id": {"type": "string"}}}),
        encoding="utf-8",
    )
    (kit_dir / "evaluation").mkdir()
    (kit_dir / "evaluation" / "golden_questions.json").write_text(
        json.dumps({"authored": "2026-08-27", "questions": [{"id": "q1"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(pipeline_kit, "KITS_DIR", tmp_path)

    stage = _stage()
    assert pipeline_kit.check_author_pass("dental", stage) is True
    assert stage.status == pipeline_kit.OK
    assert stage.todo == []


def test_an_unset_trust_tier_is_treated_as_unvouched(tmp_path, monkeypatch):
    """Absent is not a synonym for fine -- the same rule the gate applies."""
    kit_dir = tmp_path / "dental"
    kit_dir.mkdir()
    (kit_dir / "manifest.json").write_text(
        json.dumps({"id": "dental", "status": "available"}), encoding="utf-8"
    )
    monkeypatch.setattr(pipeline_kit, "KITS_DIR", tmp_path)

    stage = _stage()
    assert pipeline_kit.check_author_pass("dental", stage) is False
    assert any("unset" in note for note in stage.todo)


# -- the report ------------------------------------------------------------


def test_the_report_names_the_first_blocking_stage(capsys):
    stages = [
        pipeline_kit.Stage("K1", "intake").set(pipeline_kit.OK, "7 encoded"),
        pipeline_kit.Stage("K4", "author pass").set(
            pipeline_kit.BLOCKED, "a person", ["raise the trust tier"]
        ),
        pipeline_kit.Stage("K7", "certify").set(pipeline_kit.BLOCKED, "later"),
    ]
    code = pipeline_kit.report("dental", stages)
    out = capsys.readouterr().out

    assert code == 1
    assert "Blocked at K4 (author pass)." in out
    assert "K7" not in out.split("Blocked at")[1], "it names the FIRST blocker"


def test_blocking_at_k4_is_explained_as_expected_not_as_failure(capsys):
    stages = [pipeline_kit.Stage("K4", "author pass").set(pipeline_kit.BLOCKED, "x")]
    pipeline_kit.report("dental", stages)
    out = capsys.readouterr().out
    assert "expected terminal state" in out
    assert "nothing here will make it ready" in out


def test_attention_without_a_block_is_still_non_zero(capsys):
    """'Nothing is broken' is not the same as 'this is ready'."""
    stages = [
        pipeline_kit.Stage("K1", "intake").set(
            pipeline_kit.ATTENTION, "7 encoded, 1 dropped", ["1 item had no source"]
        )
    ]
    assert pipeline_kit.report("dental", stages) == 1
    assert "need attention" in capsys.readouterr().out


def test_only_a_fully_clean_run_reports_publishable(capsys):
    stages = [
        pipeline_kit.Stage("K1", "intake").set(pipeline_kit.OK, ""),
        pipeline_kit.Stage("K4", "author pass").set(pipeline_kit.OK, ""),
        pipeline_kit.Stage("K7", "certify").set(pipeline_kit.OK, ""),
    ]
    assert pipeline_kit.report("dental", stages) == 0
    assert "publishable: authored, vouched for, and complete" in capsys.readouterr().out


# -- intake refusal --------------------------------------------------------


def test_a_sheet_whose_items_all_lack_sources_stops_at_k1(tmp_path, monkeypatch):
    """No source, no encode -- so there is nothing to scaffold from."""
    import openpyxl
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Formulas"
    sheet.append(["item", "source", "reference"])
    sheet.append(["some unsourced claim", "", ""])
    path = tmp_path / "thin.xlsx"
    book.save(path)

    stage = pipeline_kit.Stage("K1", "intake")
    result = pipeline_kit.run_intake(
        path, "dental", "dr-hassan", tmp_path / "intake.yaml", stage
    )

    assert result is None
    assert stage.status == pipeline_kit.BLOCKED
    assert "nothing carried a source" in stage.detail
    assert not (tmp_path / "intake.yaml").exists(), "wrote an intake with nothing in it"


def test_a_sourced_sheet_produces_an_intake(tmp_path):
    import openpyxl
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Formulas"
    sheet.append(["item", "source", "reference"])
    sheet.append(["util = a / b", "company_policy", "Ops s4"])
    path = tmp_path / "ok.xlsx"
    book.save(path)

    out = tmp_path / "intake.yaml"
    stage = pipeline_kit.Stage("K1", "intake")
    document = pipeline_kit.run_intake(path, "dental", "dr-hassan", out, stage)

    assert document is not None
    assert out.is_file()
    assert stage.status == pipeline_kit.OK
    assert document["sections"]["formulas"][0]["source_ref"] == "Ops s4"


# -- publish gating --------------------------------------------------------


def test_a_kit_with_no_artifacts_is_not_reached_rather_than_failed(tmp_path, monkeypatch):
    """A scaffold declares no install artifacts yet. That is a stage not
    reached, not a stage that failed -- the distinction is the whole report."""
    kit_dir = tmp_path / "dental"
    kit_dir.mkdir()
    (kit_dir / "manifest.json").write_text(
        json.dumps({"id": "dental", "artifacts": []}), encoding="utf-8"
    )
    monkeypatch.setattr(pipeline_kit, "KITS_DIR", tmp_path)

    stage = pipeline_kit.Stage("K5", "publish")
    assert pipeline_kit.run_publish_check("dental", stage) is False
    assert stage.status == pipeline_kit.NOT_REACHED


def test_a_declared_artifact_missing_from_bundle_blocks_publish(tmp_path, monkeypatch):
    kit_dir = tmp_path / "dental"
    kit_dir.mkdir()
    (kit_dir / "manifest.json").write_text(
        json.dumps(
            {"id": "dental", "artifacts": [{"src": "gone.json", "dest": "gone.json"}]}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(pipeline_kit, "KITS_DIR", tmp_path)

    stage = pipeline_kit.Stage("K5", "publish")
    assert pipeline_kit.run_publish_check("dental", stage) is False
    assert stage.status == pipeline_kit.BLOCKED
    assert "not in bundle/" in stage.detail
