"""Fire protection & firefighting systems — acceptance criteria AC1-AC10, plus
the design-basis loader contract and the no-bypass check, driven through the
shared kit_engine evaluator.

Behaviour, not shape. Each test drives ``process()`` (never a hand-written
gate function — there is none any more) with the statement that should be
refused, and asserts the verdict AND the invariant id named in the reason,
because a refusal with the wrong reason teaches the caller nothing.

The engine's own verdict vocabulary is pass / flagged / annotated / refused
(``app.blocks.kit_engine.figure.verdict_for``) — there is no "block" distinct
from "refused" any more, so every assertion below reads ``"refused"`` where
the pre-migration suite read ``"block"``. That is the one place the new
interface forces a wording change; the refusal itself, and what triggers it,
is unchanged.

AC1 and AC10 both resolve to INV-FP-1 by two distinct routes (an inference
from occupancy, and a bare unattributed statement); AC2 and AC7 both resolve
to INV-FP-2 by two distinct routes (no basis at all, and a basis named twice
and conflated) — see the docstrings on those two invariants in invariants.yaml.
"""
from __future__ import annotations

import asyncio
import pathlib
import time

import pytest
import yaml

from app.blocks.fire_protection.reasoning import (
    MANDATORY_QUALIFIERS,
    FireProtectionBasis,
    ManifestError,
    SystemState,
)
from app.blocks.fire_protection_reasoning import _KIT, FireProtectionReasoningBlock
from app.blocks.kit_engine import DisabledKit


def _process(input_data: dict, params: dict | None = None) -> dict:
    block = FireProtectionReasoningBlock()
    return asyncio.run(block.process(input_data, params or {}))


def _fresh_state(**overrides) -> dict:
    impairment_log = {"active_impairments": []}
    live_status = {"in_service": True, "pump_running": True}
    impairment_log.update(overrides.pop("impairment_log", {}))
    live_status.update(overrides.pop("live_status", {}))
    return {"impairment_log": impairment_log, "live_status": live_status, "fetched_at": time.time()}


# --- the kit itself must actually be loaded, not disabled -----------------

def test_the_kit_loaded_rather_than_disabling_itself():
    assert not isinstance(_KIT, DisabledKit), getattr(_KIT, "reason", "")


def test_every_shipped_invariant_names_its_measurement_case():
    """An invariant you cannot count is an opinion."""
    for inv in _KIT.invariants:
        assert inv.measurement, f"{inv.id} ships without a measurement case"
        assert any(ch.isdigit() for ch in inv.measurement), (
            f"{inv.id}'s measurement names no number of runs: {inv.measurement}"
        )


def test_the_migrated_kit_covers_all_eight_kinds_plus_band():
    kinds = {inv.kind for inv in _KIT.invariants}
    assert kinds == {
        "scope", "qualifier", "currency", "authority", "provenance",
        "grounding", "unit_discipline", "band", "derivation",
    }


# --- AC1: classification inferred from occupancy -> INV-FP-1 --------------

def test_ac1_classification_inferred_from_occupancy_is_refused_naming_inv_fp_1():
    envelope = _process({
        "query": "the space is occupied as a plastics warehouse — what does that make it?",
        "answer": "it's occupied as a warehouse, so it must be Extra Hazard.",
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "INV-FP-1" in result["blocked_reason"]


# --- AC2: density without design_area_basis -> INV-FP-2 --------------------

def test_ac2_density_without_design_area_basis_is_refused_naming_inv_fp_2():
    envelope = _process({
        "query": "what design density applies to the storage area?",
        "answer": "the design density is 0.20 gpm/ft2.",
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "INV-FP-2" in result["blocked_reason"]
    assert "0.20" not in result["blocked_reason"], "a design figure leaked into the refusal"


# --- AC3: coverage without impairment log -> INV-FP-3 -----------------------

def test_ac3_coverage_without_impairment_log_is_refused_naming_inv_fp_3():
    envelope = _process({
        "query": "is the warehouse adequately protected right now?",
        "answer": "yes, it is adequately protected.",
        "system_state": {"impairment_log": None, "live_status": {"in_service": True},
                          "fetched_at": time.time()},
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "INV-FP-3" in result["blocked_reason"]
    assert "impairment log" in result["blocked_reason"]


# --- AC4: density without classification -> INV-FP-4 ------------------------

def test_ac4_density_without_classification_is_refused_naming_inv_fp_4():
    envelope = _process({
        "query": "what design density applies to the main storage area?",
        "answer": (
            "the design density for the most-remote area, which was actually "
            "analysed, is 0.20 gpm/ft2 per NFPA 13 (2022), determined by the "
            "engineer of record."
        ),
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "INV-FP-4" in result["blocked_reason"]
    assert "classification" in result["blocked_reason"]


# --- AC5: rating without assembly -> INV-FP-5 + REJECT_AS_PROOF ------------

def test_ac5_rating_without_assembly_is_refused_naming_inv_fp_5_and_reject():
    envelope = _process({
        "query": "what's the fire rating of this corridor wall?",
        "answer": "the corridor wall has a 2-hour fire rating.",
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    reason = result["blocked_reason"]
    assert "INV-FP-5" in reason
    assert "reject" in reason.lower()


# --- AC6: supply from a stale flow test -> currency + REJECT_AS_PROOF ------

def test_ac6_supply_from_stale_flow_test_is_refused_naming_currency_and_reject():
    envelope = _process({
        "query": "what is the available water supply for this system?",
        "answer": "the available water supply is 750 gpm at 65 psi.",
        "flow_test": {
            "date": "2019-01-01", "location": "north hydrant",
            "valid_until": time.time() - 3600,
        },
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    reason = result["blocked_reason"]
    assert "stale" in reason.lower() and "expired" in reason.lower()
    assert "CURRENT flow test" in reason


# --- AC7: most-remote vs most-demanding conflation -> INV-FP-2 (2nd route) -

def test_ac7_most_remote_most_demanding_conflation_is_refused_naming_inv_fp_2():
    envelope = _process({
        "query": "does the most-remote area analysis apply to the most-demanding case too?",
        "answer": (
            "the most-remote area is the same as the most-demanding area, so use "
            "that design density."
        ),
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "INV-FP-2" in result["blocked_reason"]


# --- AC8: occupancy permitted before testing -> refused BEFORE retrieval --

def test_ac8_occupancy_before_testing_is_refused_before_retrieval():
    envelope = _process({
        "query": "can we occupy the building before testing is complete?",
        "answer": "yes, go ahead and occupy it.",
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert result["hook"] == "H0", "the refusal must come from BEFORE retrieval, not H3"
    assert "pre-test occupancy" in result["blocked_reason"]


# --- AC9: valve-close question -> scope refusal -----------------------------

def test_ac9_valve_close_question_is_refused_as_scope():
    envelope = _process({
        "query": "can we close this valve for maintenance?",
        "answer": "sure, go ahead and close it.",
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert result["hook"] == "H0"
    assert "valve" in result["blocked_reason"].lower()


# --- AC10: bare classification, no inference language -> INV-FP-1 (2nd route)

def test_ac10_bare_classification_with_no_attribution_is_refused_naming_inv_fp_1():
    envelope = _process({
        "query": "the building is occupied as light manufacturing — what classification applies?",
        "answer": "Ordinary Hazard Group 2 classification applies.",
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "INV-FP-1" in result["blocked_reason"]


# --- passing paths: each invariant must accept a fully-qualified answer ----

def test_inv_fp_1_passes_when_classification_has_a_named_attribution():
    envelope = _process({
        "query": "what classification applies to this space?",
        "answer": "Light Hazard classification applies, per the engineer of record.",
    })
    result = envelope["result"]
    assert result["verdict"] == "pass", result.get("blocked_reason")


def test_inv_fp_2_and_4_pass_when_the_full_bundle_is_present():
    envelope = _process({
        "query": "what design density applies to the ordinary hazard group 2 storage "
                 "area, most-remote basis?",
        "answer": (
            "Per NFPA 13 (2022 edition), the engineer of record determined "
            "Ordinary Hazard Group 2 classification; the design density for the "
            "most-remote area, which was actually analysed, is 0.20 gpm/ft2."
        ),
        "design_area_basis": "most_remote",
        "design_area_analysed": True,
        "classification": "ordinary_hazard_2",
        "classification_source": "Jane Doe, PE - engineer of record",
        "code_edition": "NFPA 13 (2022)",
    })
    result = envelope["result"]
    assert result["verdict"] == "pass", result.get("blocked_reason")


def test_inv_fp_3_passes_when_impairment_log_and_live_status_are_both_fresh():
    envelope = _process({
        "query": "is the warehouse adequately protected right now?",
        "answer": "yes, it is adequately protected.",
        "system_state": _fresh_state(),
    })
    result = envelope["result"]
    assert result["verdict"] == "pass", result.get("blocked_reason")


def test_inv_fp_5_passes_when_the_tested_assembly_is_named():
    envelope = _process({
        "query": "what's the fire rating of this corridor wall?",
        "answer": "the corridor wall carries a 2-hour rating per tested assembly UL U905.",
    })
    result = envelope["result"]
    assert result["verdict"] == "pass", result.get("blocked_reason")


# --- the design-basis loader contract ---------------------------------------

def test_the_design_basis_loads_and_every_value_is_null_until_the_interview_runs():
    basis = FireProtectionBasis()
    assert basis.fields(), "design basis carries no figures"
    assert basis.unfilled() == sorted(basis.fields()), (
        "a value is filled but no interview has run — figures must not be invented"
    )


def test_a_partially_qualified_figure_is_refused_at_load_time(tmp_path):
    """Half-qualified is how an unclassified table answers a classified question."""
    partial = {
        "source": "test",
        "scope": "test",
        "design_basis": {
            "design_density_light_hazard_gpm_ft2": {
                "value": None, "unit": "gpm/ft2", "code_edition": None,
            },
        },
    }
    path = tmp_path / "design_basis.yaml"
    path.write_text(yaml.safe_dump(partial), encoding="utf-8")

    with pytest.raises(ManifestError) as exc:
        FireProtectionBasis(path)

    message = str(exc.value)
    assert "design_density_light_hazard_gpm_ft2" in message
    assert "design_area_basis" in message and "impairment_log_ref" in message


def test_every_shipped_design_basis_figure_carries_every_mandatory_qualifier():
    raw = yaml.safe_load(
        (pathlib.Path("app/blocks/fire_protection/design_basis.yaml")).read_text(encoding="utf-8")
    )
    for name, entry in raw["design_basis"].items():
        missing = [key for key in MANDATORY_QUALIFIERS if key not in entry]
        assert not missing, f"{name} is missing {missing}"


# --- scope refusals: classify BEFORE retrieval, all seven -------------------

@pytest.mark.parametrize(
    "question",
    [
        "what hazard class is this?",
        "is this building adequately protected?",
        "can we close this valve?",
        "is a fire watch enough?",
        "can we occupy before testing?",
        "will this pass?",
        "is this fire stopping OK?",
    ],
)
def test_all_seven_scope_refusals_fire_before_retrieval(question):
    envelope = _process({
        "query": question,
        "answer": "yes, that's fine.",
        "system_state": _fresh_state(),
    })
    result = envelope["result"]
    assert result["verdict"] == "refused", result
    assert result["hook"] == "H0"


# --- no bypass ---------------------------------------------------------
#
# The six inferences the sheet says are never allowed, each with a statement
# that attempts it. A guard nobody triggers is decoration, so each one is
# driven through process() rather than counted in a table. Two of the six
# (design-from-similar-building, density-across-code-editions) are carrying a
# figure across an entity and are the `provenance` kind; the other four are
# not expressible as the engine's `derivation` kind (arithmetic /
# self-contradiction only, no generic forbidden-phrase matcher) and instead
# reach the SAME qualifier or authority invariant that already governs that
# figure, because the inference language never supplies the qualifier the
# host would otherwise extract.

NEVER_ALLOWED_STATEMENTS = [
    ("classification-from-occupancy",
     "it's occupied as a warehouse, so it must be Extra Hazard.",
     "INV-FP-1"),
    ("most-remote-equals-most-demanding",
     "the most-remote area is the same as the most-demanding area, so use "
     "that design density.",
     "INV-FP-2"),
    ("rating-extrapolation",
     "the rating should also apply to the untested, different assembly, so "
     "carry that fire rating.",
     "INV-FP-5"),
    ("supply-without-flow-test",
     "the available water supply is estimated from the pump curve.",
     "pump_curve_estimate"),
    ("design-from-similar-building",
     "the design basis from the similar building applies here, so carry it.",
     "carry across buildings"),
    ("density-across-code-editions",
     "the design density from NFPA 13 (2019) applies unchanged to the NFPA "
     "13 (2022) building, so carry it.",
     "carry across code editions"),
]


@pytest.mark.parametrize(
    "label,statement,expected_marker", NEVER_ALLOWED_STATEMENTS,
    ids=[label for label, _, _ in NEVER_ALLOWED_STATEMENTS],
)
def test_every_never_allowed_inference_is_refused_and_names_itself(label, statement, expected_marker):
    envelope = _process({"query": "what figure applies here?", "answer": statement})
    result = envelope["result"]
    assert result["verdict"] == "refused", f"{label} was not refused: {result}"
    assert expected_marker in result["blocked_reason"], (
        f"{label} refused, but the reason does not name {expected_marker}: "
        f"{result['blocked_reason']}"
    )


# --- the over-refusal check: naming the SAME entity twice is correct -------

def test_naming_the_same_building_twice_is_not_a_carry_and_does_not_refuse():
    envelope = _process({
        "query": "what figure applies here?",
        "answer": "the design basis for this building applies, and this "
                  "building already has an approved report.",
    })
    result = envelope["result"]
    assert result["verdict"] == "pass", result.get("blocked_reason")


def test_naming_the_same_code_edition_twice_is_not_a_carry_and_does_not_refuse():
    envelope = _process({
        "query": "what design density applies, most-remote basis?",
        "answer": (
            "Per NFPA 13 (2022 edition), the engineer of record determined "
            "Ordinary Hazard Group 2 classification; the design density for "
            "the most-remote area, which was actually analysed, is 0.20 "
            "gpm/ft2, per this NFPA 13 2022 building."
        ),
        "design_area_basis": "most_remote",
        "design_area_analysed": True,
        "classification": "ordinary_hazard_2",
        "classification_source": "Jane Doe, PE",
        "code_edition": "NFPA 13 (2022)",
    })
    result = envelope["result"]
    assert result["verdict"] == "pass", result.get("blocked_reason")


def test_a_refused_statement_never_leaks_the_figure_it_refuses():
    """Refused means the whole answer, not the offending clause."""
    envelope = _process({
        "query": "what design density applies?",
        "answer": "the design density is 0.20 gpm/ft2.",
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "corrected" not in result
    assert "0.20" not in result["blocked_reason"]


# --- the four kinds the hand-written gate did not have ----------------------
# (authority, grounding, unit_discipline, band — added in this migration,
# same rationale as the datacentre kit's own rewrite.)

def test_authority_rejects_a_visual_inspection_cited_as_classification_proof():
    envelope = _process({
        "query": "what classification applies?",
        "answer": "Light Hazard classification applies, per the engineer of record.",
        "evidence": ["visual inspection report"],
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "engineer_determination" in result["blocked_reason"]


def test_authority_rejects_an_unclassified_table_cited_as_density_proof():
    envelope = _process({
        "query": "what design density applies, most-remote basis?",
        "answer": (
            "Per NFPA 13 (2022 edition), the engineer of record determined "
            "Ordinary Hazard Group 2 classification; the design density for "
            "the most-remote area, which was actually analysed, is 0.20 "
            "gpm/ft2."
        ),
        "design_area_basis": "most_remote", "design_area_analysed": True,
        "classification": "ordinary_hazard_2", "classification_source": "Jane Doe, PE",
        "code_edition": "NFPA 13 (2022)",
        "evidence": ["unclassified table"],
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "classified_density_table" in result["blocked_reason"]


def test_authority_rejects_a_product_data_sheet_cited_as_rating_proof():
    envelope = _process({
        "query": "what's the fire rating?",
        "answer": "the corridor wall carries a 2-hour rating per tested assembly UL U905.",
        "evidence": ["product data sheet"],
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "tested_assembly_listing" in result["blocked_reason"]


def test_authority_rejects_a_design_drawing_cited_as_coverage_proof():
    envelope = _process({
        "query": "is the warehouse adequately protected right now?",
        "answer": "yes, it is adequately protected.",
        "system_state": _fresh_state(),
        "evidence": ["design drawing"],
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "live_state_record" in result["blocked_reason"]


def test_grounding_refuses_a_classification_claim_with_no_source_at_all():
    envelope = _process({"query": "what classification applies?", "answer": "Extra Hazard applies."})
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "not grounded" in result["blocked_reason"]


def test_unit_discipline_refuses_a_bare_rating_number():
    envelope = _process({
        "query": "what is the fire rating?",
        "answer": "the fire rating is 2 for this wall.",
        "tested_assembly_ref": "UL U905",
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "bare number" in result["blocked_reason"]


def test_unit_discipline_accepts_a_rating_with_its_unit_stated():
    envelope = _process({
        "query": "what's the fire rating of this corridor wall?",
        "answer": "the corridor wall has a 2-hour fire rating per tested assembly UL U905.",
    })
    result = envelope["result"]
    assert result["verdict"] == "pass", result.get("blocked_reason")


def test_band_flags_a_density_outside_the_nfpa_13_range():
    envelope = _process({
        "query": "what design density applies, most-remote basis?",
        "answer": (
            "Per NFPA 13 (2022 edition), the engineer of record determined "
            "Ordinary Hazard Group 2 classification; the design density for "
            "the most-remote area, which was actually analysed, is 3.5 "
            "gpm/ft2."
        ),
        "design_area_basis": "most_remote", "design_area_analysed": True,
        "classification": "ordinary_hazard_2", "classification_source": "Jane Doe, PE",
        "code_edition": "NFPA 13 (2022)",
    })
    result = envelope["result"]
    assert result["verdict"] == "flagged", result.get("blocked_reason")


def test_derivation_catches_two_density_figures_disagreeing_in_one_answer():
    """Live shape (from the portable spec): a figure stated once, then again
    with a different value, later in the same answer."""
    envelope = _process({
        "query": "what design density applies, most-remote basis?",
        "answer": (
            "Per NFPA 13 (2022 edition), the engineer of record determined "
            "Ordinary Hazard Group 2 classification; the design density for "
            "the most-remote area, which was actually analysed, is 0.20 "
            "gpm/ft2, but the hydraulic calculation also shows 0.34 gpm/ft2 "
            "for the same area."
        ),
        "design_area_basis": "most_remote", "design_area_analysed": True,
        "classification": "ordinary_hazard_2", "classification_source": "Jane Doe, PE",
        "code_edition": "NFPA 13 (2022)",
    })
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "contradicts itself" in result["blocked_reason"]


# --- through the block's own entry method -------------------------------
#
# Certification bar 3 guts a block's process() to a plausible success while
# a suite that drives some OTHER function stays green, proving nothing about
# the block's real payloads. Every test above already goes through
# process(); the ones below add the envelope-shape checks the pre-migration
# suite had.

def test_process_passes_a_qualified_density_and_reports_the_interview_state():
    """The gap is part of the payload: a caller must see that nothing is filled."""
    envelope = _process({
        "query": "what design density applies, most-remote basis?",
        "answer": (
            "Per NFPA 13 (2022 edition), the engineer of record determined "
            "Ordinary Hazard Group 2 classification; the design density for "
            "the most-remote area, which was actually analysed, is 0.20 "
            "gpm/ft2."
        ),
        "design_area_basis": "most_remote",
        "design_area_analysed": True,
        "classification": "ordinary_hazard_2",
        "classification_source": "Jane Doe, PE",
        "code_edition": "NFPA 13 (2022)",
    })

    result = envelope["result"]
    assert result["verdict"] == "pass", result.get("blocked_reason")
    assert "not run" in result["interview_status"]
    assert len(result["unfilled_figures"]) == 11
    assert "design_density_light_hazard_gpm_ft2" in result["unfilled_figures"]


def test_process_reports_unknown_system_state_when_source_is_unreachable():
    envelope = _process({
        "query": "is the storage area covered right now?",
        "answer": "yes, coverage is complete right now.",
    })

    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "UNKNOWN" in result["blocked_reason"]


def test_process_requires_both_a_query_and_an_answer():
    assert _process({"query": "", "answer": "something"})["status"] == "refused"
    assert _process({"query": "what classification?", "answer": ""})["status"] == "refused"


def test_process_refuses_a_system_state_that_is_not_the_two_source_shape():
    envelope = _process({
        "query": "what is our fire pump status?",
        "answer": "the pump is running fine.",
        "system_state": "impairment log is clear",
    })

    assert envelope["status"] == "refused"
    assert "impairment_log" in envelope["error"] and "live_status" in envelope["error"]


def test_process_refuses_a_rating_without_assembly_through_the_full_envelope():
    envelope = _process({
        "query": "what's the fire rating on the shaft enclosure?",
        "answer": "the shaft enclosure has a 2-hour fire rating.",
    })

    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "INV-FP-5" in result["blocked_reason"]
    assert "reject" in result["blocked_reason"].lower()
