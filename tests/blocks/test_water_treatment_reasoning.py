"""Water treatment plant operations — acceptance criteria AC1-AC10, plus the
manifest loader contract and the no-bypass check. Written fail-first: every
block-severity invariant has a test that triggers it.

Behaviour, not shape. Each test drives ``gate_answer`` with the statement that
should be refused and asserts the verdict AND the named reason, because a
block with the wrong reason teaches the caller nothing.
"""
from __future__ import annotations

import pathlib
import time

import pytest
import yaml

from app.blocks.water_treatment.reasoning import (
    DERIVATION_GUARD,
    MANDATORY_QUALIFIERS,
    ManifestError,
    PlantState,
    TreatmentBasis,
    gate_answer,
)


# --- shared fixtures -------------------------------------------------------

def _fresh_state(**overrides) -> PlantState:
    scada = {
        "analyser_status": "ok",
        "calibration_due_at": time.time() + 86400,
    }
    delivery_log = {
        "delivered_strength_pct": 12.5,
        "delivered_at": time.time(),
    }
    scada.update(overrides.pop("scada", {}))
    delivery_log.update(overrides.pop("delivery_log", {}))
    return PlantState(scada=scada, delivery_log=delivery_log, fetched_at=time.time())


class _Retrieval:
    """Records every call, so a test can prove retrieval never happened."""

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, query: str):
        self.calls.append(query)
        return []


# --- AC1: CT value without temperature/pH -> INV-1 -------------------------

def test_ac1_ct_without_temperature_or_ph_is_blocked_naming_inv1():
    verdict = gate_answer(
        "what CT do we need for Giardia?",
        "CT required is 12 mg*min/L for free chlorine against Giardia, "
        "3-log inactivation target.",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "INV-1" in verdict["blocked_reason"]
    assert "temperature" in verdict["blocked_reason"]
    assert "pH" in verdict["blocked_reason"]


def test_ac1_a_fully_qualified_ct_value_is_not_blocked_by_inv1():
    """The invariant demands all five qualifiers; it must accept them."""
    verdict = gate_answer(
        "what CT do we need?",
        "CT achieved is 12 mg*min/L.",
        ct_temperature_c=5,
        ct_ph=7.5,
        disinfectant="free chlorine",
        organism="Giardia",
        log_target=3,
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "pass", verdict.get("blocked_reason")


# --- AC2: contact time without basis -> INV-2 -------------------------------

def test_ac2_contact_time_without_basis_is_blocked_naming_inv2():
    verdict = gate_answer(
        "what is the contact time for CT credit at the clearwell?",
        "the contact time is 30 minutes at 4 mgd flow with the clearwell "
        "at full tank level.",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "INV-2" in verdict["blocked_reason"]
    assert "contact_time_basis" in verdict["blocked_reason"]


def test_ac2_a_fully_qualified_contact_time_is_not_blocked_by_inv2():
    verdict = gate_answer(
        "what is the contact time for CT credit at the clearwell?",
        "the contact time is 28 minutes based on the tracer study.",
        contact_time_basis="tracer",
        flow=5.2,
        tank_level_assumed="full",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "pass", verdict.get("blocked_reason")


# --- AC3: dose without basis -> INV-3 ---------------------------------------

def test_ac3_dose_without_basis_is_blocked_naming_inv3():
    verdict = gate_answer(
        "what dose of hypochlorite are we feeding?",
        "we are feeding a dose of 2.5 mg/L of hypochlorite.",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "INV-3" in verdict["blocked_reason"]


# --- AC4: limit without regulation -> INV-4 ---------------------------------

def test_ac4_limit_without_regulation_is_blocked_naming_inv4():
    verdict = gate_answer(
        "what is the turbidity limit?",
        "the filtered water turbidity limit is 0.3 NTU as a monthly "
        "average, continuously monitored.",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "INV-4" in verdict["blocked_reason"]
    assert "regulation" in verdict["blocked_reason"]


# --- AC5 / AC6: permit stricter than code, unresolved -> INV-5 -------------

def test_ac5_permit_stricter_than_code_not_resolved_is_blocked_naming_inv5():
    verdict = gate_answer(
        "what is the distribution chlorine residual limit?",
        "the residual limit is being checked.",
        limit_sources=[
            {"source": "the NPDES permit", "value": 0.2},
            {"source": "the state drinking water code", "value": 0.5},
        ],
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "refused"
    assert "INV-5" in verdict["blocked_reason"]


def test_ac6_refuse_on_conflict_verified_names_both_sources():
    verdict = gate_answer(
        "what is the distribution chlorine residual limit?",
        "the residual limit is being checked.",
        limit_sources=[
            {"source": "the NPDES permit", "value": 0.2},
            {"source": "the state drinking water code", "value": 0.5},
        ],
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "refused"
    reason = verdict["blocked_reason"]
    assert "the NPDES permit" in reason
    assert "the state drinking water code" in reason


# --- AC7: nameplate strength used -> derivation -----------------------------

def test_ac7_nameplate_strength_used_is_blocked_as_derivation():
    verdict = gate_answer(
        "what dose are we feeding?",
        "we used the nameplate strength of the hypochlorite to calculate "
        "the dose.",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "derivation" in verdict["blocked_reason"].lower()
    assert "nameplate hypochlorite strength" in verdict["blocked_reason"]


# --- AC8: theoretical detention where T10 required -> INV-2 + reject -------

def test_ac8_theoretical_detention_where_t10_required_blocks_inv2_and_rejects():
    verdict = gate_answer(
        "what is the contact time for CT credit at the clearwell?",
        "the theoretical detention time is 42 minutes; the plant requires "
        "a T10 tracer study but none has been run.",
        contact_time_basis="theoretical",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "INV-2" in verdict["blocked_reason"]
    assert "reject" in verdict["blocked_reason"].lower()


# --- AC9: CT table interpolated -> derivation -------------------------------

def test_ac9_ct_table_interpolated_is_blocked_as_derivation():
    verdict = gate_answer(
        "what CT do we need at 8 degrees C?",
        "interpolate between the 5 degC and 10 degC rows of the CT table "
        "to get the required CT.",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "derivation" in verdict["blocked_reason"].lower()
    assert "CT table interpolation" in verdict["blocked_reason"]


# --- AC10: water-safety question refused BEFORE retrieval -------------------

def test_ac10_water_safety_question_refused_before_retrieval():
    retrieval = _Retrieval()
    verdict = gate_answer(
        "is this water safe to supply?",
        "yes, go ahead and supply it.",
        live_state=_fresh_state(),
        retrieval=retrieval,
    )
    assert verdict["verdict"] == "refused"
    assert "scope refusal" in verdict["blocked_reason"]
    assert retrieval.calls == [], "retrieval ran before the refusal classified"


@pytest.mark.parametrize(
    "question",
    [
        "can we skip filter-to-waste?",
        "do we need a boil notice?",
        "can I enter the chlorine room?",
    ],
)
def test_other_scope_refusals_are_refused_before_retrieval(question):
    retrieval = _Retrieval()
    verdict = gate_answer(
        question,
        "yes, that's fine.",
        live_state=_fresh_state(),
        retrieval=retrieval,
    )
    assert verdict["verdict"] == "refused", verdict
    assert "scope refusal" in verdict["blocked_reason"]
    assert retrieval.calls == []


# --- the manifest loader contract -------------------------------------------

def test_the_manifest_loads_and_every_value_is_null_until_the_interview_runs():
    basis = TreatmentBasis()
    assert basis.fields(), "manifest carries no figures"
    assert basis.unfilled() == sorted(basis.fields()), (
        "a value is filled but no interview has run — figures must not be invented"
    )


def test_a_partially_qualified_figure_is_refused_at_load_time(tmp_path):
    """Half-qualified is how a CT value at the wrong row answers the wrong question."""
    partial = {
        "source": "test",
        "scope": "test",
        "design_basis": {
            "ct_required_mg_min_per_l": {"value": None, "unit": "mg*min/L", "parameter": "CT_required"},
        },
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(partial), encoding="utf-8")

    with pytest.raises(ManifestError) as exc:
        TreatmentBasis(path)

    message = str(exc.value)
    assert "ct_required_mg_min_per_l" in message
    assert "regulation" in message and "dose_basis" in message


def test_every_shipped_figure_carries_every_mandatory_qualifier():
    raw = yaml.safe_load(
        (pathlib.Path("app/blocks/water_treatment/design_basis.yaml")).read_text(encoding="utf-8")
    )
    for name, entry in raw["design_basis"].items():
        missing = [key for key in MANDATORY_QUALIFIERS if key not in entry]
        assert not missing, f"{name} is missing {missing}"


# --- no bypass ---------------------------------------------------------

#: The never-allowed inferences the sheet says are never allowed, each with a
#: statement that attempts it. A guard nobody triggers is decoration, so each
#: one is driven through the real gate rather than counted in a table.
NEVER_ALLOWED_STATEMENTS = [
    ("CT table interpolation",
     "interpolate between the 5 degC and 10 degC rows of the CT table to "
     "get the required CT."),
    ("nameplate hypochlorite strength",
     "we used the nameplate strength of the hypochlorite to calculate the "
     "dose."),
    ("design-document compliance",
     "the design document shows we are in compliance with the limit."),
    ("PLANT TRAP",
     "Plant A's CT table is the same as Plant B's, so apply it."),
]


def test_the_derivation_guard_names_itself_in_every_reason():
    for name, pattern, reason in DERIVATION_GUARD:
        assert name and reason, "a guard entry must name itself in the reason"


@pytest.mark.parametrize("label,statement", NEVER_ALLOWED_STATEMENTS,
                         ids=[label for label, _ in NEVER_ALLOWED_STATEMENTS])
def test_every_never_allowed_inference_blocks_and_names_itself(label, statement):
    verdict = gate_answer(
        "can we use Plant B's CT table?" if "Plant" in statement else "what figure applies here?",
        statement,
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block", f"{label} was not blocked: {verdict}"
    reason = verdict["blocked_reason"]
    assert label in reason, (
        f"{label} blocked, but the reason does not name which inference: {reason}"
    )


def test_theoretical_detention_where_t10_required_is_never_allowed():
    verdict = gate_answer(
        "what is the contact time for CT credit at the clearwell?",
        "the theoretical detention time is 42 minutes; the plant requires "
        "a T10 tracer study but none has been run.",
        contact_time_basis="theoretical",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "theoretical-detention-where-t10-required" in verdict["blocked_reason"]


def test_naming_the_same_plant_twice_is_not_blocked_as_a_carry():
    """Naming the SAME plant twice is what a correct answer looks like."""
    verdict = gate_answer(
        "what dose applies at Plant A?",
        "Plant A's dose is 2.5 mg/L as-active with a delivered strength of "
        "12.5%. Plant A confirms this reading.",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "pass", verdict.get("blocked_reason")


def test_a_blocked_statement_never_returns_a_figure():
    """Block means the whole answer, not the offending clause."""
    verdict = gate_answer(
        "what is the CT achieved?",
        "CT achieved is 12 mg*min/L.",
        live_state=_fresh_state(),
    )
    assert verdict["verdict"] == "block"
    assert "corrected" not in verdict


# --- through the block's own entry method -------------------------------
#
# The tests above drive gate_answer. Certification bar 3 gutted
# OffshoreMarineReasoningBlock.process to a plausible success and the suite
# stayed GREEN -- proving nothing about the block's payloads (see
# tests/blocks/test_offshore_marine_reasoning.py). These tests go through
# process() and assert on what it returns, so a gutted entry method goes red.

import asyncio

from app.blocks.water_treatment_reasoning import WaterTreatmentReasoningBlock


def _process(input_data: dict, params: dict | None = None) -> dict:
    block = WaterTreatmentReasoningBlock()
    return asyncio.run(block.process(input_data, params or {}))


def test_process_refuses_a_water_safety_question_and_names_the_scope_refusal():
    envelope = _process({
        "query": "is this water safe to supply?",
        "answer": "yes, it's fine.",
    })

    assert envelope["block_id"] == "water_treatment_reasoning"
    assert envelope["status"] == "success"
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "scope refusal" in result["blocked_reason"]
    assert "named-person decision" in result["blocked_reason"]


def test_process_blocks_a_ct_value_missing_qualifiers_naming_inv1():
    envelope = _process({
        "query": "what CT do we need for Giardia?",
        "answer": "CT required is 12 mg*min/L.",
    })

    result = envelope["result"]
    assert result["verdict"] == "block"
    assert "INV-1" in result["blocked_reason"]


def test_process_passes_a_qualified_dose_and_reports_the_interview_state():
    """The gap is part of the payload: a caller must see that nothing is filled."""
    envelope = _process({
        "query": "what dose applies?",
        "answer": "the dose is 2.5 mg/L as-active with a delivered strength "
        "of 12.5%.",
    })

    result = envelope["result"]
    assert result["verdict"] == "pass", result.get("blocked_reason")
    assert "not run" in result["interview_status"]
    assert len(result["unfilled_figures"]) == 9
    assert "ct_required_mg_min_per_l" in result["unfilled_figures"]


def test_process_reports_unknown_plant_state_when_scada_is_absent():
    envelope = _process({
        "query": "what is the current chlorine residual right now?",
        "answer": "the residual is 1.2 mg/L.",
    })

    result = envelope["result"]
    assert result["verdict"] == "block"
    assert "UNKNOWN" in result["blocked_reason"]
    assert "1.2" not in result["blocked_reason"], "a design figure leaked into the refusal"


def test_process_blocks_inv5_conflict_naming_both_sources():
    envelope = _process({
        "query": "what is the distribution chlorine residual limit?",
        "answer": "the residual limit is being checked.",
        "limit_sources": [
            {"source": "the discharge permit", "value": 0.2},
            {"source": "the state code", "value": 0.5},
        ],
    })

    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "INV-5" in result["blocked_reason"]
    assert "the discharge permit" in result["blocked_reason"]
    assert "the state code" in result["blocked_reason"]


def test_process_requires_both_a_query_and_an_answer():
    assert _process({"query": "", "answer": "something"})["status"] == "refused"
    assert _process({"query": "what dose?", "answer": ""})["status"] == "refused"


def test_process_refuses_a_live_state_that_is_not_the_two_source_shape():
    envelope = _process({
        "query": "what is our CT?",
        "answer": "12 mg*min/L.",
        "live_state": "scada is fine",
    })

    assert envelope["status"] == "refused"
    assert "scada" in envelope["error"] and "delivery_log" in envelope["error"]
