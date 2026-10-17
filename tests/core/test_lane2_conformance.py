"""The store-wide conformance report, and the promise that it never reds.

The report-only promise is the load-bearing part. Cowork is booting generated
zips from this store right now; a check that measures pre-contract code and
fails the build would stop the critical path to report a backlog everybody
already knows about. So this file pins the promise in a test, where quietly
revoking it costs a failing suite rather than a surprised colleague.

The checks themselves are tested against synthetic classes rather than the
real registry, so they prove the LOGIC. Whether any particular block conforms
is what the report is for, and is not asserted here -- a test that pinned
today's numbers would have to be edited every time somebody fixed a block.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "lane2_conformance.py"
WORKFLOW = ROOT / ".github" / "workflows" / "lane2-conformance.yml"


def _load():
    spec = importlib.util.spec_from_file_location("lane2_conformance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["lane2_conformance"] = module
    spec.loader.exec_module(module)
    return module


conformance = _load()


# -- the promise -----------------------------------------------------------


def test_the_report_returns_zero_even_when_every_check_fails(monkeypatch, capsys):
    """REPORT-ONLY, asserted rather than asserted-to.

    If a later change makes this script exit non-zero, it stops being a
    report and becomes a gate -- and it would become one silently, on a
    branch nobody was watching.
    """
    everything_broken = [
        conformance.Row(block, check, conformance.FAIL, "planted")
        for block in ("alpha", "beta")
        for check in conformance.CHECKS
    ]
    monkeypatch.setattr(conformance, "collect", lambda **kwargs: everything_broken)
    monkeypatch.setattr(sys, "argv", ["lane2_conformance.py", "--summary-only"])

    assert conformance.main() == 0
    assert "REPORT-ONLY" in capsys.readouterr().out


def test_the_workflow_does_not_gate_anything():
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = document["jobs"]["conformance"]["steps"]
    commands = "\n".join(step.get("run", "") for step in steps)

    assert "exit 1" not in commands
    assert "|| exit" not in commands
    # No step may turn the script's zero into a failure by re-checking it.
    assert "grep -q fail" not in commands


def test_the_workflow_runs_on_stacked_pull_requests():
    """ci.yml only triggers on PRs based on main, which leaves a stacked
    Lane 2 PR with no table at all."""
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML reads the bare key `on:` as the boolean True.
    triggers = document.get("on", document.get(True))
    assert "pull_request" in triggers
    assert not (triggers.get("pull_request") or {}).get("branches"), (
        "a base-branch filter would silence the report on stacked PRs"
    )


# -- (a) Liskov constructor conformance -----------------------------------


class _Conformant:
    name = "conformant"

    def __init__(self, hal_block=None, config=None):
        pass


class _Narrowed:
    """The #88 shape: a required positional the base class never promised."""

    name = "narrowed"

    def __init__(self, hal_block, config=None):
        pass


class _KeywordOnly:
    name = "keyword_only"

    def __init__(self, *, hal_block=None, config=None):
        pass


def test_a_block_matching_the_base_signature_conforms():
    assert conformance.check_constructor(_Conformant).status == conformance.PASS


def test_a_narrowed_constructor_is_reported():
    row = conformance.check_constructor(_Narrowed)
    assert row.status == conformance.FAIL
    assert "hal_block" in row.note


def test_the_note_says_which_call_shape_failed():
    """A reader must be able to act on the row without opening the class."""
    row = conformance.check_constructor(_Narrowed)
    assert "does not accept ()" in row.note


def test_keyword_only_still_conforms():
    """The base class is called with keywords everywhere in this repo, so
    keyword-only is not a narrowing."""
    assert conformance.check_constructor(_KeywordOnly).status == conformance.PASS


# -- (b) the minimal input is declared, never invented --------------------


def test_requires_inputs_is_used_when_the_manifest_declares_it(monkeypatch):
    monkeypatch.setattr(
        conformance,
        "_manifest_for",
        lambda name: {
            "requires_inputs": [
                {"name": "boq_file", "type": "file"},
                {"name": "rates", "type": "json"},
            ]
        },
    )
    assert conformance.minimal_input("x") == {"boq_file": "", "rates": {}}


def test_required_legacy_inputs_are_the_fallback(monkeypatch):
    monkeypatch.setattr(
        conformance,
        "_manifest_for",
        lambda name: {
            "inputs": [
                {"name": "needed", "type": "string", "required": True},
                {"name": "optional", "type": "string", "required": False},
            ]
        },
    )
    assert conformance.minimal_input("x") == {"needed": ""}


def test_a_block_that_declares_nothing_is_invoked_with_nothing(monkeypatch):
    """The honest minimum. Inventing a payload would test a call nobody
    makes, and would hide the block that cannot cope with an empty one."""
    monkeypatch.setattr(conformance, "_manifest_for", lambda name: None)
    assert conformance.minimal_input("x") == {}


# -- (c) three tests present ----------------------------------------------


def test_a_block_with_no_test_file_is_reported(monkeypatch):
    monkeypatch.setattr(conformance, "_candidate_test_files", lambda name, cls: [])
    row = conformance.check_three_tests("lonely", _Conformant)
    assert row.status == conformance.FAIL
    assert "no test file" in row.note


def test_a_test_file_missing_a_category_names_which_one(tmp_path, monkeypatch):
    path = tmp_path / "test_partial.py"
    path.write_text(
        "def test_happy_path(): pass\n"
        "def test_it_raises_on_bad_input(): pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        conformance, "_candidate_test_files", lambda name, cls: [path]
    )
    row = conformance.check_three_tests("partial", _Conformant)

    assert row.status == conformance.FAIL
    assert "mutation_probe" in row.note
    assert "happy" not in row.note.split("(")[0]


# -- (d) / (e) K2 / K3 report-only ----------------------------------------


class _RagTagged:
    name = "raggy"
    tags = ["knowledge", "rag"]


class _NotRag:
    name = "plain"
    tags = ["infrastructure"]


def test_non_rag_blocks_are_skipped_for_k2_and_k3():
    assert conformance.check_source_class_render("plain", _NotRag).status == conformance.SKIP
    assert conformance.check_coverage_honesty("plain", _NotRag).status == conformance.SKIP


def test_a_rag_block_using_the_answer_contract_passes_k2(tmp_path, monkeypatch):
    path = tmp_path / "rag_block.py"
    path.write_text(
        "from app.core.answer_contract import emit_chunk, source_class\n"
        "class X:\n    tags = ['rag']\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        conformance.inspect, "getmodule", lambda cls: type("M", (), {"__file__": str(path)})()
    )
    row = conformance.check_source_class_render("raggy", _RagTagged)
    assert row.status == conformance.PASS


def test_a_rag_block_missing_the_coverage_line_is_reported(tmp_path, monkeypatch):
    path = tmp_path / "rag_block.py"
    path.write_text("class X:\n    tags = ['rag']\n", encoding="utf-8")
    monkeypatch.setattr(
        conformance.inspect, "getmodule", lambda cls: type("M", (), {"__file__": str(path)})()
    )
    row = conformance.check_coverage_honesty("raggy", _RagTagged)
    assert row.status == conformance.FAIL
    assert "coverage_line" in row.note


def test_a_file_with_all_three_categories_passes(tmp_path, monkeypatch):
    path = tmp_path / "test_full.py"
    path.write_text(
        "# happy path\n# planted failure\n# mutation probe\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        conformance, "_candidate_test_files", lambda name, cls: [path]
    )
    assert conformance.check_three_tests("full", _Conformant).status == conformance.PASS


# -- (f) L2.2 brief-scope, report-only ------------------------------------


def test_brief_scope_is_in_the_report_and_empty_lists_pass(monkeypatch):
    monkeypatch.setattr(
        conformance,
        "_manifest_for",
        lambda name: {"reads": [], "writes": [], "never": [], "acceptance": []},
    )
    row = conformance.check_brief_scope("measured")
    assert row.status == conformance.PASS
    assert "reads=empty" in row.note


def test_brief_scope_reports_missing_fields(monkeypatch):
    monkeypatch.setattr(conformance, "_manifest_for", lambda name: {"id": "x"})
    row = conformance.check_brief_scope("bare")
    assert row.status == conformance.FAIL
    assert "missing" in row.note
    assert "reads" in row.note


def test_brief_scope_reports_invalid_fields(monkeypatch):
    monkeypatch.setattr(
        conformance,
        "_manifest_for",
        lambda name: {
            "reads": [{"kind": "vibes", "scope": "x"}],
            "writes": [],
            "never": [],
            "acceptance": [],
        },
    )
    row = conformance.check_brief_scope("bad")
    assert row.status == conformance.FAIL
    assert "invalid" in row.note


def test_brief_scope_reports_a_missing_manifest(monkeypatch):
    monkeypatch.setattr(conformance, "_manifest_for", lambda name: None)
    row = conformance.check_brief_scope("ghost")
    assert row.status == conformance.FAIL
    assert "no block.json" in row.note


# -- the table -------------------------------------------------------------


def _rows():
    return [
        conformance.Row("alpha", "constructor", conformance.PASS),
        conformance.Row("beta", "constructor", conformance.FAIL, "narrowed"),
        conformance.Row("beta", "smoke", conformance.PASS, "status=refused"),
        conformance.Row("beta", "three_tests", conformance.FAIL, "no test file found"),
    ]


def test_the_table_has_the_columns_the_order_asked_for():
    table = conformance.render(_rows())
    assert "| block | check | result | note |" in table


def test_non_conformers_come_first_and_are_counted():
    table = conformance.render(_rows())
    assert "### Non-conformers (2)" in table
    assert table.index("Non-conformers") < table.index("<details>")


def test_conforming_rows_are_folded_away_but_not_dropped():
    """No silent truncation: a reader can still see everything that passed."""
    table = conformance.render(_rows())
    assert "<details><summary>Conforming (2)</summary>" in table
    assert "`alpha`" in table


def test_an_import_failure_is_flagged_as_environmental_not_as_a_verdict():
    rows = [
        conformance.Row(
            "gamma", "constructor", conformance.FAIL, "import failed: no numpy"
        )
    ]
    table = conformance.render(rows)
    assert "could not be imported in this environment" in table
    assert "`gamma`" in table


def test_a_pipe_in_a_note_cannot_break_the_table():
    rows = [conformance.Row("delta", "smoke", conformance.FAIL, "a | b")]
    assert "a \\| b" in conformance.render(rows)


def test_the_baseline_names_every_non_conformer_under_its_check():
    baseline = conformance.render_baseline(_rows())
    assert "### `constructor` (1)" in baseline
    assert "- `beta` — narrowed" in baseline
    assert "### `smoke` (0)" in baseline


def test_the_baseline_says_it_should_be_read_from_ci():
    assert "Generated in CI" in conformance.render_baseline(_rows())
