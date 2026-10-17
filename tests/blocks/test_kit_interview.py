"""The interview: the domain owner's own question sheets, as the kits carry them.

The sheets in ``docs/kit_questions/`` are the record of what was asked for, in the
owner's words. ``app/blocks/<kit>/questions.yaml`` is a GENERATED view of them. The
first test here is therefore the important one: it regenerates every file from its
sheet and fails if what is committed differs. Without it the YAML is a second copy
of the same fact, free to drift, and a hand-edit that quietly reworded a [GATE]
question into a [GAP] would never be caught.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest
import yaml

from app.blocks.kit_engine import (
    DisabledKit,
    Interview,
    InterviewError,
    load_kit,
    parse_interview,
)
from app.blocks.kit_engine.engine import KitLoadError

ROOT = pathlib.Path(__file__).resolve().parents[2]
BLOCKS = ROOT / "app" / "blocks"
SHEETS = ROOT / "docs" / "kit_questions"

#: The two kits with no owner question sheet. Neither is un-interviewed: both have
#: their OWN figure register (design_basis.yaml), and datacentre's is filled in.
#: Named so that adding an eighteenth kit with neither fails here.
WITHOUT_SHEET = {"datacentre", "offshore_marine", "stadium_venue"}


def _importer():
    spec = importlib.util.spec_from_file_location(
        "kit_question_importer", ROOT / "scripts" / "import_kit_questions.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def kit_dirs():
    return sorted(
        p.parent for p in BLOCKS.glob("*/manifest.yaml")
        if (p.parent / "invariants.yaml").is_file()
    )


#: EVERY kit's figure register is its own design_basis.yaml (operating_basis for
#: og_operations). Six were built with one; the other eleven got a generated
#: per-quantity `figures:` block in the manifest instead, which could not say "this
#: value is meaningless without its train and its averaging basis" -- and which,
#: written over the one FILLED register, reported datacentre's 17-of-18 answered
#: facility as a kit with nothing answered. There is now one register per kit and
#: no manifest carries a figures block.
WITH_REGISTER = {d.name for d in kit_dirs()}

#: The six whose register was authored by hand and is the record. The other eleven
#: are generated from each kit's own manifest, invariants and question sheet.
HAND_WRITTEN_REGISTERS = {"datacentre", "fire_protection", "offshore_marine",
                          "og_operations", "rail", "water_treatment"}


def sheet_kits():
    """One entry per kit sheet. A sheet is named for its kit, so anything in the
    directory that is not a kit directory is documentation about the sheets rather
    than one of them."""
    return sorted(
        p.stem for p in SHEETS.glob("*.md")
        if (BLOCKS / p.stem / "manifest.yaml").is_file()
    )


# --------------------------------------------------------------------------
# the drift guard
# --------------------------------------------------------------------------

@pytest.mark.parametrize("kit", sheet_kits())
def test_committed_questions_match_the_sheet_exactly(kit):
    """Regenerate from the markdown and compare. A hand-edit fails here."""
    imp = _importer()
    sheet = SHEETS / f"{kit}.md"
    manifest = yaml.safe_load((BLOCKS / kit / "manifest.yaml").read_text(encoding="utf-8")) or {}
    title, answer_format, sections, questions = imp.parse_sheet(sheet)
    for question in questions:
        question["covers"] = imp._covers(question["text"], manifest.get("quantities") or {})
    expected = imp.render(kit, sheet, title, answer_format, sections, questions)
    committed = (BLOCKS / kit / "questions.yaml").read_text(encoding="utf-8")
    assert committed == expected, (
        f"{kit}/questions.yaml has drifted from docs/kit_questions/{kit}.md. "
        f"Edit the sheet and re-run scripts/import_kit_questions.py; never hand-edit the YAML."
    )


@pytest.mark.parametrize("kit", sheet_kits())
def test_every_question_text_is_verbatim_from_the_sheet(kit):
    """The wording is the owner's. A paraphrase is a different question."""
    sheet_text = (SHEETS / f"{kit}.md").read_text(encoding="utf-8")
    normalised = " ".join(sheet_text.split())
    interview = load_kit(BLOCKS / kit).interview
    for question in interview.questions:
        assert " ".join(question.text.split()) in normalised, (
            f"{kit} {question.id}: text is not in the sheet verbatim: {question.text[:70]}"
        )


@pytest.mark.parametrize("kit", sheet_kits())
def test_gate_and_gap_counts_match_the_sheets_own_marks(kit):
    sheet_text = (SHEETS / f"{kit}.md").read_text(encoding="utf-8")
    interview = load_kit(BLOCKS / kit).interview
    assert sum(1 for q in interview.questions if q.gate is True) == len(
        re.findall(r"\[GATE\]", sheet_text))
    assert sum(1 for q in interview.questions if q.gate is False) == len(
        re.findall(r"\[GAP\]", sheet_text))


def test_every_sheet_is_installed_and_the_kits_without_one_are_named():
    installed = {d.name for d in kit_dirs() if (d / "questions.yaml").is_file()}
    missing = {d.name for d in kit_dirs()} - installed
    assert installed == set(sheet_kits())
    assert missing == WITHOUT_SHEET, (
        f"kits with no owner question sheet: {sorted(missing)}. Add the sheet, or add "
        f"the kit to WITHOUT_SHEET so it is a stated gap and not an oversight."
    )


# --------------------------------------------------------------------------
# answers never live in the kit
# --------------------------------------------------------------------------

@pytest.mark.parametrize("kit", sheet_kits())
def test_no_questions_file_holds_an_answer(kit):
    """The kit is a signed Store block shared by every customer. One client's
    figures arriving inside another's kit is the provenance failure this whole
    layer exists to prevent, and it would arrive signed."""
    raw = yaml.safe_load((BLOCKS / kit / "questions.yaml").read_text(encoding="utf-8"))
    for question in raw["questions"]:
        for forbidden in ("answer", "value", "answered_by", "answered_at"):
            assert forbidden not in question, (
                f"{kit} {question['id']} has an '{forbidden}' slot in the kit"
            )


# --------------------------------------------------------------------------
# gating
# --------------------------------------------------------------------------

def test_unmarked_questions_gate_because_an_unreadable_class_must_block():
    interview = load_kit(BLOCKS / "fm").interview
    unmarked = [q for q in interview.questions if q.gate is None]
    assert unmarked, "the FM sheet marks nothing; it is the case this rule exists for"
    assert all(q.gating for q in unmarked)
    assert all(q.marked == "unmarked" for q in unmarked), (
        "an unmarked question must still be distinguishable from one the owner marked GATE"
    )


def test_a_gap_question_never_blocks_readiness():
    interview = load_kit(BLOCKS / "fitout").interview
    gaps = [q for q in interview.questions if q.gate is False]
    assert gaps
    # Answer every gating question and nothing else: ready, with GAPs outstanding.
    answers = {q.id: "x" for q in interview.questions if q.gating}
    assert interview.ready(answers)
    assert interview.gaps(answers) == tuple(gaps)


def test_one_outstanding_gate_question_is_enough_to_block():
    interview = load_kit(BLOCKS / "fitout").interview
    gating = [q for q in interview.questions if q.gating]
    answers = {q.id: "x" for q in gating[1:]}
    assert not interview.ready(answers)
    assert interview.outstanding(answers) == (gating[0],)


def test_outstanding_is_in_sheet_order_not_sorted():
    """The owner grouped these from rates to incidents. Asked out of order the
    interview reads as a random quiz."""
    interview = load_kit(BLOCKS / "rail").interview
    out = [q.id for q in interview.outstanding({})]
    assert out != sorted(out)
    order = [q.id for q in interview.questions]
    assert out == [qid for qid in order if qid in set(out)]


def test_an_answer_to_a_question_the_sheet_never_asked_is_named():
    interview = load_kit(BLOCKS / "fitout").interview
    status = interview.status({"B.1": "x", "NOT.A.QUESTION": "x"})
    assert status["answers_to_unknown_questions"] == ["NOT.A.QUESTION"]
    assert status["answered"] == 1, "an unknown id must not count toward answered"


# --------------------------------------------------------------------------
# the shape of a complete answer, per domain
# --------------------------------------------------------------------------

def test_required_fields_come_from_the_sheets_answer_format_line():
    fitout = load_kit(BLOCKS / "fitout").interview
    assert fitout.required_fields() == (
        "unit", "quality_band", "market", "source", "date", "confirmed_or_indicative")
    # "value" is the answer itself, not a field that must accompany it.
    assert "value" not in fitout.required_fields()


def test_each_domain_demands_its_own_fields_not_a_shared_list():
    dental = load_kit(BLOCKS / "dental").interview.required_fields()
    fire = load_kit(BLOCKS / "fire_protection").interview.required_fields()
    assert "adult_or_paediatric" in dental and "protocol_version" in dental
    assert "code_edition" in fire
    assert set(dental) != set(fire), (
        "if every domain demanded the same fields there would be no reason to read "
        "the sheet's answer-format line at all"
    )


def test_required_fields_are_names_the_manifest_already_uses_where_they_overlap():
    """The mapping from the sheet's prose to a field key is mechanical, which only
    holds because the manifests already spell them the same way."""
    kit = load_kit(BLOCKS / "fitout")
    assert "confirmed_or_indicative" in kit.manifest.qualifier_fields
    assert "quality_band" in kit.manifest.qualifier_fields
    assert "market" in kit.manifest.qualifier_fields


# --------------------------------------------------------------------------
# fail closed
# --------------------------------------------------------------------------

def test_a_sheet_that_will_not_parse_disables_the_kit(tmp_path):
    src = BLOCKS / "fitout"
    for name in ("manifest.yaml", "invariants.yaml"):
        (tmp_path / name).write_text((src / name).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "questions.yaml").write_text("kit: fitout\nquestions: []\n", encoding="utf-8")
    with pytest.raises(KitLoadError) as exc:
        load_kit(tmp_path)
    assert "questions" in str(exc.value).lower()


def test_an_interview_belonging_to_another_kit_disables_rather_than_asks(tmp_path):
    """Asking one domain's questions while gating another's figures is worse than
    not loading."""
    src = BLOCKS / "fitout"
    for name in ("manifest.yaml", "invariants.yaml"):
        (tmp_path / name).write_text((src / name).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "questions.yaml").write_text(
        (BLOCKS / "rail" / "questions.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(KitLoadError) as exc:
        load_kit(tmp_path)
    assert "rail" in str(exc.value) and "fitout" in str(exc.value)


def test_an_interview_with_no_answer_format_is_refused():
    with pytest.raises(InterviewError) as exc:
        parse_interview({
            "kit": "x",
            "questions": [{"id": "1.1", "text": "?", "gate": True}],
        })
    assert "answer_format" in str(exc.value)


def test_a_bad_gate_value_is_refused_rather_than_read_as_false():
    with pytest.raises(InterviewError):
        parse_interview({
            "kit": "x", "answer_format": ["value", "source"],
            "questions": [{"id": "1.1", "text": "?", "gate": "yes"}],
        })


# --------------------------------------------------------------------------
# what a caller sees
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_one_kit_with_a_filled_register_reports_as_answered():
    """datacentre has no question sheet and does not need one: its OWN figure
    register, design_basis.yaml, is filled in from the completed encoding sheet for
    facility_01. An earlier version reported it as `derived` with nothing answered,
    which called the one answered domain in the Store an empty one -- while the
    file sat in the same directory."""
    from app.blocks.datacentre_kit import DatacentreKitBlock
    out = await DatacentreKitBlock().process(
        {"figures": [{"quantity": "pue", "value": 1.4}]}, {})
    state = out["result"]["interview"]
    assert state["questions_source"] == "design_basis"
    assert state["sheet_supplied"] is False
    assert state["design_basis_supplied"] is True
    assert state["interview_ran"] is True, "17 of 18 figures are answered"
    register = state["design_basis"]
    assert register["answered"] == 17 and register["figures"] == 18
    assert register["open_figures"] == ["pue_guaranteed"]
    assert register["facility"] == "facility_01"
    assert "facility_01" in state["note"]
    assert "derived" not in state["note"]


@pytest.mark.asyncio
async def test_a_kit_whose_register_is_an_empty_template_says_no_interview_has_run():
    """Five of the six registers are declared and empty. Empty is not "nothing to
    ask" -- it is everything still to ask."""
    from app.blocks.offshore_marine_kit import OffshoreMarineKitBlock
    out = await OffshoreMarineKitBlock().process(
        {"figures": [{"quantity": "crane_swl", "value": 1, "unit": "t"}]}, {})
    state = out["result"]["interview"]
    assert state["questions_source"] == "design_basis"
    assert state["interview_ran"] is False
    assert state["ready"] is False
    assert state["design_basis"]["answered"] == 0
    assert "no interview has run" in state["note"]


@pytest.mark.asyncio
async def test_a_kit_with_both_a_register_and_a_sheet_reports_both_as_required():
    """They are not alternatives: the register holds this asset's figures, the
    sheet asks the organisation's rules."""
    from app.blocks.rail_kit import RailKitBlock
    out = await RailKitBlock().process(
        {"figures": [{"quantity": "twist", "value": 3, "unit": "mm"}]}, {})
    state = out["result"]["interview"]
    assert state["questions_source"] == "design_basis+owner_sheet"
    assert state["design_basis"]["figures"] == 10
    assert state["questions"] == 82
    assert "Both have to be answered" in state["note"]


@pytest.mark.asyncio
async def test_a_kit_with_neither_a_sheet_nor_a_register_says_its_questions_are_derived():
    from app.blocks.aesthetic_kit import AestheticKitBlock
    out = await AestheticKitBlock().process(
        {"figures": [{"quantity": "units", "value": 20}]}, {})
    state = out["result"]["interview"]
    # aesthetic HAS a sheet, so prove the derived branch on its own terms instead.
    assert state["sheet_supplied"] is True


@pytest.mark.asyncio
async def test_a_kit_with_a_sheet_reports_the_owners_questions_and_what_is_next():
    from app.blocks.fitout_kit import FitoutKitBlock
    out = await FitoutKitBlock().process(
        {"figures": [{"quantity": "rate", "value": 1, "unit": "currency_per_m2"}]}, {})
    state = out["result"]["interview"]
    assert state["questions_source"] == "design_basis+owner_sheet", (
        "every kit now carries its own figure register alongside the owner's sheet"
    )
    assert state["sheet_supplied"] is True
    assert state["design_basis_supplied"] is True
    assert state["questions"] == 62
    assert state["ready"] is False
    first = state["next"][0]
    assert first["id"] == "B.1" and first["marked"] == "GATE"
    assert "quality band" in first["text"]


def test_covers_links_a_question_to_a_quantity_only_on_an_exact_naming():
    """A fuzzy link would report a figure as asked when nothing asks it."""
    interview = load_kit(BLOCKS / "rail").interview
    covered = {c for q in interview.questions for c in q.covers}
    quantities = set(load_kit(BLOCKS / "rail").manifest.quantities)
    assert covered <= quantities
    assert interview.for_quantity("face_pressure"), "the rail sheet names face pressure"
    assert not interview.for_quantity("no_such_quantity")


# --------------------------------------------------------------------------
# a kit's own figure register
# --------------------------------------------------------------------------

def test_every_kit_has_exactly_one_figure_register_and_it_is_the_design_basis():
    found = {d.name for d in kit_dirs() if (d / "design_basis.yaml").is_file()}
    assert found == WITH_REGISTER, (
        f"kits with no figure register: {sorted(WITH_REGISTER - found)}. Run "
        f"scripts/generate_kit_registers.py."
    )
    carrying_both = [
        d.name for d in kit_dirs()
        if (yaml.safe_load((d / "manifest.yaml").read_text(encoding="utf-8")) or {}).get("figures")
    ]
    assert not carrying_both, (
        f"{carrying_both} carry BOTH a register and a manifest figures block — the "
        f"same fact in two places, free to disagree"
    )


@pytest.mark.parametrize("kit", sorted(WITH_REGISTER))
def test_a_kit_with_its_own_register_carries_no_generated_figures_block(kit):
    """The generated block is a second, worse copy of a register that exists. On
    datacentre it reported 9 unanswered figures for a facility that had answered
    17 of 18 -- an answered domain presented as an empty one, while the real file
    sat in the same directory."""
    manifest = yaml.safe_load(
        (BLOCKS / kit / "manifest.yaml").read_text(encoding="utf-8")) or {}
    assert not manifest.get("figures"), (
        f"{kit} has both a design_basis.yaml and a generated figures block. Run "
        f"scripts/add_figure_questions.py, which now skips register kits."
    )


@pytest.mark.parametrize("kit", sorted(WITH_REGISTER))
def test_every_register_loads_and_accounts_for_itself(kit):
    basis = load_kit(BLOCKS / kit).design_basis
    assert basis is not None
    assert basis.figures, "a register with no figures reads as nothing to answer"
    assert len(basis.answered) + len(basis.open) == len(basis.figures)
    assert basis.scope, "a register must declare its own scope; these never carry"


def test_datacentre_is_the_one_filled_register_and_reports_as_answered():
    basis = load_kit(BLOCKS / "datacentre").design_basis
    assert basis.ran is True
    assert len(basis.answered) == 17 and basis.open == ("pue_guaranteed",)
    assert basis.facility == "facility_01"
    assert basis.value_of("generator_fuel_autonomy_hours") == 120
    assert basis.value_of("pue_design") == 1.4


@pytest.mark.parametrize("kit", sorted(WITH_REGISTER - {"datacentre"}))
def test_the_other_registers_are_declared_and_empty_which_is_not_nothing_to_ask(kit):
    basis = load_kit(BLOCKS / kit).design_basis
    assert basis.ran is False
    assert not basis.answered
    assert basis.open == tuple(basis.figures), "every figure is still to be answered"


def test_a_register_naming_no_recognised_block_disables_the_kit(tmp_path):
    src = BLOCKS / "fitout"
    for name in ("manifest.yaml", "invariants.yaml"):
        (tmp_path / name).write_text(
            (src / name).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "design_basis.yaml").write_text(
        "source: somewhere\nscope: somewhere\n", encoding="utf-8")
    with pytest.raises(KitLoadError) as exc:
        load_kit(tmp_path)
    assert "figure register" in str(exc.value)


def test_the_generator_refuses_to_write_over_a_register(tmp_path):
    """The guard that stops this recurring, exercised rather than trusted."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "add_figure_questions.py"), "--check"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert result.returncode == 0, result.stderr
    for kit in sorted(WITH_REGISTER):
        assert kit in result.stdout
    assert "design_basis.yaml, which IS their" in result.stdout


def test_the_figure_generator_is_idempotent():
    """It said so in its docstring and was not: the blank lines preceding the block
    survived the strip, so every run added one more to every kit. A generator that
    churns its own output makes each re-run a diff nobody can review."""
    import shutil
    import subprocess
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        before = {}
        for kit in kit_dirs():
            path = kit / "manifest.yaml"
            copy = pathlib.Path(tmp) / f"{kit.name}.yaml"
            shutil.copy2(path, copy)
            before[kit.name] = path.read_bytes()

        for _ in range(2):
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "add_figure_questions.py")],
                capture_output=True, text=True, cwd=str(ROOT))
            assert result.returncode == 0, result.stderr

        try:
            after = {kit.name: (kit / "manifest.yaml").read_bytes() for kit in kit_dirs()}
            churned = sorted(n for n in before if before[n] != after[n])
            assert not churned, (
                f"re-running the generator changed {churned} — it is not idempotent"
            )
        finally:
            for kit in kit_dirs():
                shutil.copy2(pathlib.Path(tmp) / f"{kit.name}.yaml", kit / "manifest.yaml")
