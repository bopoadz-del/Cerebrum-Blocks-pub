"""Railway & Metro Construction — acceptance criteria AC1-AC10, plus the
design-basis loader contract and the no-bypass check. Written fail-first:
every block-severity invariant has a test that triggers it.

Behaviour, not shape. Each test drives ``gate_answer`` with the statement
that should be refused and asserts the verdict AND the named reason, because
a block with the wrong reason teaches the caller nothing.

``gate_answer`` is now the shared kit_engine, wired up in
app.blocks.rail_reasoning: it builds Figure objects from these same
arguments, evaluates them against app/blocks/rail/manifest.yaml +
invariants.yaml, and translates the Outcome back into this module's
pass/block/refused shape. The domain vocabulary (TrackBasis, TrackState, the
four never-declarative derivation-guard entries) still lives in
app.blocks.rail.reasoning.
"""
from __future__ import annotations

import pathlib
import time

import pytest
import yaml

from app.blocks.rail.reasoning import (
    DERIVATION_GUARD,
    MANDATORY_QUALIFIERS,
    ManifestError,
    TrackBasis,
    TrackState,
)
from app.blocks.rail_reasoning import gate_answer


# --- shared fixtures -------------------------------------------------------

def _fresh_state(**overrides) -> TrackState:
    possession_system = {
        "possessions": [],
        "isolations": [],
        "tsrs": [],
    }
    manual_log = {
        "protection_arrangements": [],
        "disturbed_at": None,
    }
    possession_system.update(overrides.pop("possession_system", {}))
    manual_log.update(overrides.pop("manual_log", {}))
    return TrackState(possession_system=possession_system, manual_log=manual_log, fetched_at=time.time())


def _good_tbm(**overrides) -> dict:
    band = {
        "chainage_min_m": 4000,
        "chainage_max_m": 5000,
        "ground_basis": "ground model rev 3",
    }
    band.update(overrides)
    return band


def _good_clearance(**overrides) -> dict:
    clearance = {
        "envelope_type": "structure_gauge",
        "cant": 150,
        "curve_radius": 800,
    }
    clearance.update(overrides)
    return clearance


class _Retrieval:
    """Records every call, so a test can prove retrieval never happened."""

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, query: str):
        self.calls.append(query)
        return []


# --- AC1: geometry limit without tier + line_speed -> INV-1 ---------------

def test_ac1_geometry_limit_without_tier_or_speed_is_blocked_naming_inv1():
    verdict = gate_answer(
        "what is the twist limit here?",
        "the twist limit is 5 mm.",
        category="plain_line",
    )
    assert verdict["verdict"] == "block"
    assert "INV-1" in verdict["blocked_reason"]


def test_ac1_a_fully_qualified_geometry_limit_is_not_blocked_by_inv1():
    """The invariant demands tier AND line_speed; it must accept both."""
    verdict = gate_answer(
        "what is the twist limit here?",
        "the twist limit is 5 mm.",
        category="plain_line",
        tier="safety",
        line_speed=60,
    )
    assert verdict["verdict"] == "pass", verdict.get("blocked_reason")


# --- AC2: SFT without disturbance state -> INV-2 + INV-3 -------------------

def test_ac2_sft_without_disturbance_state_is_blocked_naming_inv2_and_inv3():
    verdict = gate_answer(
        "what is the SFT?",
        "the SFT is 27 degC.",
        route="Down Main",
        sft_verified_date="2024-01-01",
        method="stressing record",
    )
    assert verdict["verdict"] == "block"
    assert "INV-2" in verdict["blocked_reason"]
    assert "INV-3" in verdict["blocked_reason"]


def test_ac2_a_fully_qualified_sft_figure_is_not_blocked():
    verdict = gate_answer(
        "what is the SFT?",
        "the SFT is 27 degC.",
        route="Down Main",
        sft_verified_date="2024-01-01",
        method="stressing record",
        disturbed_since=False,
    )
    assert verdict["verdict"] == "pass", verdict.get("blocked_reason")


# --- AC3: twist carried without base length -> reject ---------------------

def test_ac3_twist_without_base_length_is_blocked_by_the_derivation_guard():
    verdict = gate_answer(
        "what twist do we carry forward?",
        "we carry the twist reading without recording its base length in the handover.",
    )
    assert verdict["verdict"] == "block"
    assert "never-allowed derivation" in verdict["blocked_reason"]
    assert "base length" in verdict["blocked_reason"]


# --- AC4: face pressure out of chainage band -> INV-5 ----------------------

def test_ac4_face_pressure_out_of_chainage_band_is_blocked_naming_inv5():
    verdict = gate_answer(
        "what face pressure applies at chainage 5200m?",
        "hold the face pressure between 2.1 and 2.4 bar.",
        tbm=_good_tbm(),
        chainage_m=5200,
    )
    assert verdict["verdict"] == "block"
    assert "INV-5" in verdict["blocked_reason"]
    assert "outside the scheduled band" in verdict["blocked_reason"]


def test_ac4_face_pressure_without_a_chainage_band_is_blocked_naming_inv5():
    verdict = gate_answer(
        "what face pressure applies?",
        "hold the face pressure between 2.1 and 2.4 bar.",
        tbm=None,
    )
    assert verdict["verdict"] == "block"
    assert "INV-5" in verdict["blocked_reason"]


def test_ac4_face_pressure_inside_the_chainage_band_is_not_blocked():
    verdict = gate_answer(
        "what face pressure applies at chainage 4500m?",
        "hold the face pressure between 2.1 and 2.4 bar.",
        tbm=_good_tbm(),
        chainage_m=4500,
    )
    assert verdict["verdict"] == "pass", verdict.get("blocked_reason")


# --- AC5: handback without disturbance check -> INV-3 ----------------------

def test_ac5_handback_speed_without_disturbance_check_is_blocked_naming_inv3():
    verdict = gate_answer(
        "what handback speed applies?",
        "the handback speed is 40 mph.",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "INV-3" in verdict["blocked_reason"]


def test_ac5_handback_speed_with_a_known_disturbance_state_is_not_blocked():
    verdict = gate_answer(
        "what handback speed applies?",
        "the handback speed is 40 mph.",
        live_state=_fresh_state(),
        disturbed_since=False,
    )
    assert verdict["verdict"] == "pass", verdict.get("blocked_reason")


# --- AC6: clearance without envelope -> INV-4 ------------------------------

def test_ac6_clearance_without_envelope_is_blocked_naming_inv4():
    verdict = gate_answer(
        "what is the clearance here?",
        "the clearance is 350 mm.",
    )
    assert verdict["verdict"] == "block"
    assert "INV-4" in verdict["blocked_reason"]


def test_ac6_a_fully_qualified_clearance_is_not_blocked():
    verdict = gate_answer(
        "what is the clearance here?",
        "the clearance is 350 mm.",
        clearance=_good_clearance(),
        line_speed=100,
    )
    assert verdict["verdict"] == "pass", verdict.get("blocked_reason")


# --- AC7: adjacent-line-open without approved SSOW -> refusal -------------

def test_ac7_adjacent_line_open_is_refused_naming_ssow():
    retrieval = _Retrieval()
    verdict = gate_answer(
        "is it safe to work with adjacent line open?",
        "yes, proceed.",
        retrieval=retrieval,
    )
    assert verdict["verdict"] == "refused"
    assert "refused before retrieval" in verdict["blocked_reason"]
    assert "adjacent line open" in verdict["blocked_reason"]
    assert "SSOW" in verdict["blocked_reason"]
    assert retrieval.calls == [], "retrieval ran before the refusal classified"


# --- AC8: TSR from plan not current notice -> staleness --------------------

def test_ac8_tsr_from_the_possession_plan_is_blocked_as_stale():
    verdict = gate_answer(
        "what TSR applies here?",
        "the TSR of 20 mph applies, per the possession plan.",
        live_state=_fresh_state(),
        disturbed_since=True,
    )
    assert verdict["verdict"] == "block"
    assert "staleness" in verdict["blocked_reason"].lower()
    assert "current notice" in verdict["blocked_reason"]


# --- AC9: clearance scaled from drawing -> derivation + reject -------------

def test_ac9_clearance_scaled_from_a_drawing_is_blocked_naming_derivation_and_reject():
    verdict = gate_answer(
        "what clearance applies?",
        "we scaled the clearance off the design drawing.",
    )
    assert verdict["verdict"] == "block"
    assert "never-allowed derivation" in verdict["blocked_reason"]
    assert "REJECT_AS_PROOF" in verdict["blocked_reason"]


# --- AC10: handback question refused BEFORE retrieval ----------------------

def test_ac10_handback_tonight_is_refused_before_retrieval():
    retrieval = _Retrieval()
    verdict = gate_answer(
        "can we hand the line back tonight?",
        "yes, go ahead.",
        live_state=_fresh_state(),
        retrieval=retrieval,
    )
    assert verdict["verdict"] == "refused", verdict
    assert "refused before retrieval" in verdict["blocked_reason"]
    assert retrieval.calls == [], "retrieval ran before the refusal classified"


@pytest.mark.parametrize(
    "question",
    [
        "can we hand the line back tonight?",
        "is it safe to work with adjacent line open?",
        "can we put the crane here?",
        "can we stress the rail today?",
        "is this building at risk?",
        "can we go into the four-foot?",
    ],
)
def test_all_scope_refusals_are_refused_before_retrieval(question):
    retrieval = _Retrieval()
    verdict = gate_answer(
        question,
        "yes, go ahead.",
        live_state=_fresh_state(),
        retrieval=retrieval,
    )
    assert verdict["verdict"] == "refused", verdict
    assert "refused before retrieval" in verdict["blocked_reason"]
    assert "SSOW" in verdict["blocked_reason"]
    assert retrieval.calls == [], f"retrieval ran before refusing: {question}"


# --- the manifest loader contract ------------------------------------------

def test_the_manifest_loads_and_every_value_is_null_until_the_interview_runs():
    basis = TrackBasis()
    assert basis.fields(), "manifest carries no figures"
    assert basis.unfilled() == sorted(basis.fields()), (
        "a value is filled but no interview has run — figures must not be invented"
    )


def test_a_partially_qualified_figure_is_refused_at_load_time(tmp_path):
    """Half-qualified is how a maintenance-tier limit answers a safety-tier
    question."""
    partial = {
        "source": "test",
        "scope": "test",
        "design_basis": {
            "twist_limit_mm": {"value": None, "unit": "mm", "category": "plain_line"},
        },
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(partial), encoding="utf-8")

    with pytest.raises(ManifestError) as exc:
        TrackBasis(path)

    message = str(exc.value)
    assert "twist_limit_mm" in message
    assert "tier" in message and "line_speed" in message


def test_every_shipped_figure_carries_every_mandatory_qualifier():
    raw = yaml.safe_load(
        (pathlib.Path("app/blocks/rail/design_basis.yaml")).read_text(encoding="utf-8")
    )
    for name, entry in raw["design_basis"].items():
        missing = [key for key in MANDATORY_QUALIFIERS if key not in entry]
        assert not missing, f"{name} is missing {missing}"


# --- no bypass ---------------------------------------------------------
#
# The six inferences the sheet says are never allowed, each with a statement
# that attempts it. A guard nobody triggers is decoration, so each one is
# driven through the real gate rather than counted in a table. Two of the six
# (categories, assets) are checked with distinct-value extraction rather than
# a counting regex — naming the SAME category or asset twice is what a
# correct answer looks like.

NEVER_ALLOWED_STATEMENTS = [
    ("SFT from installation temperature",
     "infer the SFT from the installation temperature."),
    ("scale clearances off drawings",
     "we scaled the clearance off the design drawing."),
    ("carry face pressure from similar drive",
     "apply the face pressure from the similar drive here."),
    ("carry twist without base length",
     "carry the twist figure without stating its base length."),
    ("interpolate geometry limits across categories",
     "interpolate the plain line limit and the tunnel limit between the two categories."),
    ("carry triggers between assets",
     "carry the trigger from building A to building B, apply the same trigger level."),
]


def test_the_derivation_guard_names_itself_in_every_reason():
    for name, pattern, reason in DERIVATION_GUARD:
        assert name and reason, "a guard entry must name itself in the reason"


@pytest.mark.parametrize("label,statement", NEVER_ALLOWED_STATEMENTS,
                         ids=[label for label, _ in NEVER_ALLOWED_STATEMENTS])
def test_every_never_allowed_inference_blocks_and_names_itself(label, statement):
    verdict = gate_answer(
        "what figure applies here?",
        statement,
    )
    assert verdict["verdict"] == "block", f"{label} was not blocked: {verdict}"
    reason = verdict["blocked_reason"]
    assert label in reason, (
        f"{label} blocked, but the reason does not name which inference: {reason}"
    )


def test_a_blocked_statement_never_returns_a_figure():
    """Block means the whole answer, not the offending clause."""
    verdict = gate_answer(
        "what is the SFT?",
        "the SFT is 27 degC.",
        route="Down Main",
    )
    assert verdict["verdict"] == "block"
    assert "corrected" not in verdict
    assert "27" not in verdict["blocked_reason"]


# --- through the block's own entry method -------------------------------
#
# The tests above drive gate_answer. Certification bar 3 gutted
# RailReasoningBlock.process to a plausible success and the suite must go
# red for that. These tests go through process() and assert on what it
# returns, so a gutted entry method goes red.

import asyncio

from app.blocks.rail_reasoning import RailReasoningBlock


def _process(input_data: dict, params: dict | None = None) -> dict:
    block = RailReasoningBlock()
    return asyncio.run(block.process(input_data, params or {}))


def test_process_refuses_a_go_decision_and_names_the_scope_refusal():
    envelope = _process({"query": "can we hand the line back tonight?", "answer": "yes, go ahead."})

    assert envelope["block_id"] == "rail_reasoning"
    assert envelope["status"] == "success"
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "refused before retrieval" in result["blocked_reason"]
    assert "SSOW" in result["blocked_reason"]


def test_process_blocks_a_geometry_limit_without_tier_naming_inv1():
    envelope = _process({
        "query": "what is the twist limit?",
        "answer": "the twist limit is 5 mm.",
        "category": "plain_line",
    })

    result = envelope["result"]
    assert result["verdict"] == "block"
    assert "INV-1" in result["blocked_reason"]


def test_process_passes_a_benign_answer_and_reports_the_interview_state():
    """The gap is part of the payload: a caller must see that nothing is filled."""
    envelope = _process({
        "query": "what is the general status report?",
        "answer": "all normal.",
    })

    result = envelope["result"]
    assert result["verdict"] == "pass", result.get("blocked_reason")
    assert "not run" in result["interview_status"]
    assert len(result["unfilled_figures"]) == 10
    assert "twist_limit_mm" in result["unfilled_figures"]


def test_process_reports_unknown_track_state_when_possession_system_is_absent():
    envelope = _process({
        "query": "what is our current TSR status right now?",
        "answer": "TSR is 20 mph.",
    })

    result = envelope["result"]
    assert result["verdict"] == "block"
    assert "UNKNOWN" in result["blocked_reason"]
    assert "20" not in result["blocked_reason"]


def test_process_surfaces_live_preconditions_rather_than_answering_around_them():
    envelope = _process({
        "query": "what is the current isolation status?",
        "answer": "the isolation status is confirmed clear.",
        "live_state": {
            "possession_system": {
                "possessions": ["poss-123"],
                "isolations": ["iso-9"],
                "tsrs": [],
            },
            "manual_log": {"protection_arrangements": []},
        },
    })

    result = envelope["result"]
    assert result["verdict"] == "pass", result.get("blocked_reason")
    corrected = result["corrected"]
    assert corrected["live_preconditions"]["isolations"] == ["iso-9"]
    assert corrected["live_preconditions"]["possessions"] == ["poss-123"]


def test_process_requires_both_a_query_and_an_answer():
    assert _process({"query": "", "answer": "something"})["status"] == "refused"
    assert _process({"query": "what twist limit?", "answer": ""})["status"] == "refused"


def test_process_refuses_a_live_state_that_is_not_the_two_source_shape():
    envelope = _process({
        "query": "what is our current TSR status?",
        "answer": "20 mph.",
        "live_state": "possession system is fine",
    })

    assert envelope["status"] == "refused"
    assert "possession_system" in envelope["error"] and "manual_log" in envelope["error"]
