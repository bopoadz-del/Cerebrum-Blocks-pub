"""Offshore marine operations — acceptance criteria AC1–AC10, plus the manifest
loader contract and the no-bypass check. Written fail-first: every
block-severity invariant has a test that triggers it.

Behaviour, not shape. Each test drives ``gate_answer`` with the statement that
should be refused and asserts the verdict AND the named reason, because a block
with the wrong reason teaches the caller nothing.
"""
from __future__ import annotations

import pathlib
import time

import pytest
import yaml

from app.blocks.offshore_marine.reasoning import (
    DERIVATION_GUARD,
    MANDATORY_QUALIFIERS,
    InstallationBasis,
    ManifestError,
    SpreadState,
    gate_answer,
)


# --- shared fixtures -------------------------------------------------------

def _fresh_state(**overrides) -> SpreadState:
    monitoring = {
        "dp": "ok",
        "thrusters": "6 of 6",
        "generators": "ok",
        "references": "ok",
        "tension": "ok",
    }
    manual_log = {
        "isolations": [],
        "components_out": [],
        "stinger_as_set": {"radius_m": 120, "recorded_at": time.time()},
    }
    monitoring.update(overrides.pop("monitoring", {}))
    manual_log.update(overrides.pop("manual_log", {}))
    return SpreadState(monitoring=monitoring, manual_log=manual_log, fetched_at=time.time())


def _good_forecast() -> dict:
    return {
        "horizon_hours": 48,
        "confidence": 0.8,
        "operation_duration_hours": 12,
        "contingency_hours": 6,
        "window_covers": True,
    }


class _Retrieval:
    """Records every call, so a test can prove retrieval never happened."""

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, query: str):
        self.calls.append(query)
        return []


# --- AC1: single-sided tension -> INV-1 ------------------------------------

def test_ac1_single_sided_tension_is_blocked_naming_inv1():
    verdict = gate_answer(
        "what top tension do we hold on the S-lay spread?",
        "hold a lay tension of 850 kN.",
        spread_type="s_lay",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "INV-1" in verdict["blocked_reason"]
    assert "band" in verdict["blocked_reason"].lower()


def test_ac1_a_real_band_is_not_blocked_by_inv1():
    """The invariant demands a band; it must accept one."""
    verdict = gate_answer(
        "what top tension range applies on the S-lay spread?",
        "hold a lay tension between 780 and 900 kN on the s_lay spread.",
        spread_type="s_lay",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "pass", verdict.get("blocked_reason")


# --- AC2: allowable without static/dynamic -> INV-2 ------------------------

def test_ac2_allowable_without_static_or_dynamic_is_blocked_naming_inv2():
    verdict = gate_answer(
        "what is the allowable strain?",
        "the allowable strain in the overbend is 0.25%.",
        spread_type="s_lay",
        region="overbend",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "INV-2" in verdict["blocked_reason"]


def test_ac2_allowable_without_region_is_blocked_naming_inv2():
    verdict = gate_answer(
        "what is the allowable strain?",
        "the dynamic allowable strain is 0.25%.",
        spread_type="s_lay",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "INV-2" in verdict["blocked_reason"]


# --- AC3: cross-spread carry -> INV-3 -------------------------------------

def test_ac3_cross_spread_envelope_carry_is_blocked():
    verdict = gate_answer(
        "can we use the J-lay envelope?",
        "the s_lay envelope is the same as the j_lay envelope, so apply it.",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "spread" in verdict["blocked_reason"].lower()


def test_ac3_envelope_without_spread_type_is_blocked_naming_inv3():
    verdict = gate_answer(
        "what is the operating envelope?",
        "the operating envelope is 2.0 m to 2.5 m Hs.",
        live_state=_fresh_state(),
        forecast=_good_forecast(),
    )
    assert verdict["verdict"] == "block"
    assert "INV-3" in verdict["blocked_reason"]


# --- AC4: DP capability without live state -> INV-4 -----------------------

def test_ac4_dp_capability_without_live_state_ref_is_blocked_naming_inv4():
    verdict = gate_answer(
        "what is our DP capability?",
        "DP capability in the intact case is 2.8 m Hs.",
        spread_type="j_lay",
        failure_case="intact",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "INV-4" in verdict["blocked_reason"]
    assert "live_state_ref" in verdict["blocked_reason"]


def test_ac4_dp_capability_without_failure_case_is_blocked_naming_inv4():
    verdict = gate_answer(
        "what is our station-keeping capability?",
        "station-keeping capability is 2.8 m Hs.",
        spread_type="j_lay",
        live_state_ref="spread-state-2026-09-24T06:00Z",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "INV-4" in verdict["blocked_reason"]
    assert "failure_case" in verdict["blocked_reason"]


# --- AC5: go-decision refused BEFORE retrieval ---------------------------

@pytest.mark.parametrize(
    "question",
    [
        "can we start the lift?",
        "can we start the pull-in?",
        "can we commence the lay?",
        "is the weather OK?",
        "can we run on two thrusters?",
        "is it safe to dive?",
        "can we get closer?",
    ],
)
def test_ac5_go_decisions_are_refused_before_retrieval(question):
    retrieval = _Retrieval()
    verdict = gate_answer(
        question,
        "yes, go ahead.",
        live_state=_fresh_state(),
        retrieval=retrieval,
    )
    assert verdict["verdict"] == "refused", verdict
    assert "scope refusal" in verdict["blocked_reason"]
    assert retrieval.calls == [], "retrieval ran before the refusal classified"


# --- AC6: Hs-only weather check -> REJECT_AS_PROOF -----------------------

def test_ac6_hs_alone_is_rejected_as_proof_of_a_weather_criterion():
    verdict = gate_answer(
        "are we inside the weather criteria?",
        "conditions are inside the criteria.",
        spread_type="j_lay",
        live_state=_fresh_state(),
        forecast=_good_forecast(),
        evidence=["Hs alone from the 06:00 forecast"],
    )
    assert verdict["verdict"] == "block"
    assert "REJECT_AS_PROOF" in verdict["blocked_reason"] or "not acceptable evidence" in verdict["blocked_reason"]


# --- AC7: static-to-dynamic -> derivation guard --------------------------

def test_ac7_static_to_dynamic_is_blocked_by_the_derivation_guard():
    verdict = gate_answer(
        "can we use the static allowable?",
        "the static allowable applies to the dynamic case as well, so use it.",
        spread_type="s_lay",
        region="overbend",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "static" in verdict["blocked_reason"] and "dynamic" in verdict["blocked_reason"]
    assert "never-allowed derivation" in verdict["blocked_reason"]


# --- AC8: monitoring down -> UNKNOWN, no design figure ------------------

def test_ac8_monitoring_down_reports_unknown_and_no_design_figure():
    verdict = gate_answer(
        "what is our current DP capability right now?",
        "DP capability is 2.8 m Hs.",
        spread_type="j_lay",
        live_state=None,
    )
    assert verdict["verdict"] == "block"
    reason = verdict["blocked_reason"]
    assert "UNKNOWN" in reason
    assert "no design-basis fallback" in reason or "has no design-basis fallback" in reason
    assert "2.8" not in reason, "a design figure leaked into the refusal"


# --- AC9: manual log stale -> both-sources block ------------------------

def test_ac9_missing_manual_log_blocks_naming_both_sources():
    state = SpreadState(monitoring={"dp": "ok"}, manual_log=None, fetched_at=time.time())
    verdict = gate_answer(
        "what is the current thruster state?",
        "all six thrusters are available.",
        spread_type="j_lay",
        live_state=state,
    )
    assert verdict["verdict"] == "block"
    assert "manual log" in verdict["blocked_reason"]
    assert "both" in verdict["blocked_reason"].lower()


def test_ac9_stale_live_state_blocks_naming_both_sources():
    state = SpreadState(
        monitoring={"dp": "ok"},
        manual_log={"components_out": []},
        fetched_at=time.time() - 7200,
    )
    verdict = gate_answer(
        "what is the current thruster state?",
        "all six thrusters are available.",
        spread_type="j_lay",
        live_state=state,
    )
    assert verdict["verdict"] == "block"
    assert "both" in verdict["blocked_reason"].lower()


# --- AC10: sister-vessel plot cited -> VESSEL TRAP ----------------------

def test_ac10_sister_vessel_citation_is_blocked_as_a_vessel_trap():
    verdict = gate_answer(
        "what tension range can we hold?",
        "hold 780 to 900 kN on the s_lay spread.",
        spread_type="s_lay",
        live_state=_fresh_state(),
        evidence=["capability plot from the sister vessel"],
    )
    assert verdict["verdict"] == "block"
    assert "VESSEL TRAP" in verdict["blocked_reason"]


# --- the manifest loader contract --------------------------------------

def test_the_manifest_loads_and_every_value_is_null_until_the_interview_runs():
    basis = InstallationBasis()
    assert basis.fields(), "manifest carries no figures"
    assert basis.unfilled() == sorted(basis.fields()), (
        "a value is filled but no interview has run — figures must not be invented"
    )


def test_a_partially_qualified_figure_is_refused_at_load_time(tmp_path):
    """Half-qualified is how a sagbend allowable answers an overbend question."""
    partial = {
        "source": "test",
        "scope": "test",
        "design_basis": {
            "lay_tension_min_kn": {"value": None, "unit": "kN", "spread_type": "s_lay"},
        },
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(partial), encoding="utf-8")

    with pytest.raises(ManifestError) as exc:
        InstallationBasis(path)

    message = str(exc.value)
    assert "lay_tension_min_kn" in message
    assert "region" in message and "analysis_rev" in message


def test_every_shipped_figure_carries_every_mandatory_qualifier():
    raw = yaml.safe_load(
        (pathlib.Path("app/blocks/offshore_marine/design_basis.yaml")).read_text(encoding="utf-8")
    )
    for name, entry in raw["design_basis"].items():
        missing = [key for key in MANDATORY_QUALIFIERS if key not in entry]
        assert not missing, f"{name} is missing {missing}"


# --- no bypass ---------------------------------------------------------

#: The ten inferences the sheet says are never allowed, each with a statement
#: that attempts it. A guard nobody triggers is decoration, so each one is
#: driven through the real gate rather than counted in a table.
NEVER_ALLOWED_STATEMENTS = [
    ("depth-range extrapolation",
     "extrapolate the figure beyond the analysed water depth range."),
    ("static-to-dynamic",
     "the static allowable applies to the dynamic case as well, so use it."),
    ("post-failure DP from intact plot",
     "read it off the intact plot with a thruster out."),
    ("cross-spread envelope carry",
     "the s_lay envelope is the same as the j_lay envelope."),
    ("rigid envelope on flexible or cable",
     "apply the rigid pipe envelope to the flexible riser."),
    ("crane SWL across configuration",
     "the SWL holds at a different radius and boom configuration."),
    ("sister-vessel carry",
     "take the figure from the sister vessel."),
    ("depth-band carry",
     "the route figure from another depth band applies here, so carry it."),
    ("window without alpha",
     "the weather window is fine on the raw forecast, without alpha applied."),
    ("mixed-source sea state",
     "combine Hs from this forecast with Tp from another source."),
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
        spread_type="s_lay",
        region="overbend",
        static_or_dynamic="dynamic",
        failure_case="intact",
        live_state_ref="spread-state-ref",
        live_state=_fresh_state(),
        forecast=_good_forecast(),
    )
    assert verdict["verdict"] == "block", f"{label} was not blocked: {verdict}"
    reason = verdict["blocked_reason"]
    assert label in reason or "VESSEL TRAP" in reason, (
        f"{label} blocked, but the reason does not name which inference: {reason}"
    )


def test_a_blocked_statement_never_returns_a_figure():
    """Block means the whole answer, not the offending clause."""
    verdict = gate_answer(
        "what is the allowable strain?",
        "the allowable strain is 0.25%.",
        spread_type="s_lay",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "corrected" not in verdict
    assert "0.25" not in verdict["blocked_reason"]


# --- through the block's own entry method -------------------------------
#
# The tests above drive gate_answer. Certification bar 3 gutted
# OffshoreMarineReasoningBlock.process to a plausible success and the suite
# stayed GREEN -- proving nothing about the block's payloads. These tests go
# through process() and assert on what it returns, so a gutted entry method
# goes red.

import asyncio

from app.blocks.offshore_marine_reasoning import OffshoreMarineReasoningBlock


def _process(input_data: dict, params: dict | None = None) -> dict:
    block = OffshoreMarineReasoningBlock()
    return asyncio.run(block.process(input_data, params or {}))


def test_process_refuses_a_go_decision_and_names_the_scope_refusal():
    envelope = _process({"query": "can we start the lift?", "answer": "yes, go ahead."})

    assert envelope["block_id"] == "offshore_marine_reasoning"
    assert envelope["status"] == "success"
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "scope refusal" in result["blocked_reason"]
    assert "named-person decision" in result["blocked_reason"]


def test_process_blocks_a_single_sided_tension_naming_inv1():
    envelope = _process({
        "query": "what top tension do we hold?",
        "answer": "hold a lay tension of 850 kN.",
        "spread_type": "s_lay",
        "live_state": {"monitoring": {"dp": "ok"}, "manual_log": {"components_out": []}},
    })

    result = envelope["result"]
    assert result["verdict"] == "block"
    assert "INV-1" in result["blocked_reason"]


def test_process_passes_a_qualified_band_and_reports_the_interview_state():
    """The gap is part of the payload: a caller must see that nothing is filled."""
    envelope = _process({
        "query": "what tension range applies?",
        "answer": "hold 780 to 900 kN on the s_lay spread.",
        "spread_type": "s_lay",
        "live_state": {"monitoring": {"dp": "ok"}, "manual_log": {"components_out": []}},
    })

    result = envelope["result"]
    assert result["verdict"] == "pass", result.get("blocked_reason")
    assert "not run" in result["interview_status"]
    assert len(result["unfilled_figures"]) == 11
    assert "lay_tension_min_kn" in result["unfilled_figures"]


def test_process_reports_unknown_spread_state_when_monitoring_is_absent():
    envelope = _process({
        "query": "what is our current DP capability right now?",
        "answer": "DP capability is 2.8 m Hs.",
        "spread_type": "j_lay",
    })

    result = envelope["result"]
    assert result["verdict"] == "block"
    assert "UNKNOWN" in result["blocked_reason"]
    assert "2.8" not in result["blocked_reason"]


def test_process_surfaces_the_degraded_transition_rather_than_inferring_it():
    envelope = _process({
        "query": "what is the current thruster state?",
        "answer": "the spread is available.",
        "spread_type": "j_lay",
        # A thruster-state question IS a station-keeping question, so INV-4
        # applies: the failure case and the live-state reference are part of
        # asking it properly, not extras.
        "failure_case": "one thruster out",
        "live_state_ref": "spread-state-2026-09-24T06:00Z",
        "live_state": {
            "monitoring": {"dp": "ok", "thrusters": "5 of 6"},
            "manual_log": {
                "components_out": [{"component": "thruster-3", "since": time.time() - 1800}]
            },
        },
    })

    result = envelope["result"]
    assert result["verdict"] == "pass", result.get("blocked_reason")
    corrected = result["corrected"]
    assert corrected["degraded_from"] == "N+1" and corrected["degraded_to"] == "N"
    assert corrected["degraded_component"] == "thruster-3"
    assert corrected["time_in_degraded_seconds"] >= 1800


def test_process_requires_both_a_query_and_an_answer():
    assert _process({"query": "", "answer": "something"})["status"] == "refused"
    assert _process({"query": "what tension?", "answer": ""})["status"] == "refused"


def test_process_refuses_a_live_state_that_is_not_the_two_source_shape():
    envelope = _process({
        "query": "what is our DP capability?",
        "answer": "2.8 m Hs.",
        "live_state": "monitoring is fine",
    })

    assert envelope["status"] == "refused"
    assert "monitoring" in envelope["error"] and "manual_log" in envelope["error"]
