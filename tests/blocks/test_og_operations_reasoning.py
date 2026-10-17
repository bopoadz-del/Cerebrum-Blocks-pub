"""Oil & gas operations — acceptance criteria AC1-AC11, plus the manifest
loader contract and the no-bypass check. Written fail-first: every
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

from app.blocks.og_operations.reasoning import (
    DERIVATION_GUARD,
    MANDATORY_QUALIFIERS,
    LiveState,
    ManifestError,
    OperatingBasis,
    gate_answer,
)


# --- shared fixtures -------------------------------------------------------

def _fresh_state(**overrides) -> LiveState:
    monitoring = {"sce_status": "armed", "trip": "armed"}
    manual_log = {"override_register": [], "isolation_register": [], "permit_register": []}
    monitoring.update(overrides.pop("monitoring", {}))
    manual_log.update(overrides.pop("manual_log", {}))
    return LiveState(monitoring=monitoring, manual_log=manual_log, fetched_at=time.time())


class _Retrieval:
    """Records every call, so a test can prove retrieval never happened."""

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, query: str):
        self.calls.append(query)
        return []


# --- AC1: pressure without which-pressure -> INV-1 -------------------------

def test_ac1_pressure_without_which_pressure_is_blocked_naming_inv1():
    verdict = gate_answer(
        "what is the pressure?",
        "the pressure is 250 psig.",
    )
    assert verdict["verdict"] == "block"
    assert "INV-1" in verdict["blocked_reason"]


def test_ac1_a_fully_qualified_pressure_figure_is_not_blocked_by_inv1():
    """The invariant demands which-pressure, gauge|absolute and location; it
    must accept a statement that actually carries all three."""
    verdict = gate_answer(
        "what is the MAWP?",
        "the MAWP at V-101 is 285 psig, gauge.",
    )
    assert verdict["verdict"] == "pass", verdict.get("blocked_reason")


# --- AC2: envelope without tier -> INV-2 ------------------------------------

def test_ac2_envelope_without_tier_is_blocked_naming_inv2():
    verdict = gate_answer(
        "what's the setpoint?",
        "the setpoint is 300 psig.",
    )
    assert verdict["verdict"] == "block"
    assert "INV-2" in verdict["blocked_reason"]


def test_ac2_envelope_with_tier_named_is_not_blocked_by_inv2():
    verdict = gate_answer(
        "what's the high alarm setpoint?",
        "the high alarm setpoint is 300 psig.",
    )
    assert verdict["verdict"] == "pass", verdict.get("blocked_reason")


# --- AC3: SCE answer with override register missing -> INV-3 ---------------

def test_ac3_sce_answer_missing_override_register_is_blocked_naming_inv3():
    verdict = gate_answer(
        "what is the current status of the ESD trip on V-101?",
        "the ESD trip is active and isolated.",
        live_state=_fresh_state(),
        isolation_register_ref="ISO-2024-118",
    )
    assert verdict["verdict"] == "block"
    assert "INV-3" in verdict["blocked_reason"]
    assert "override_register_ref" in verdict["blocked_reason"]


def test_ac3_sce_answer_with_both_registers_is_not_blocked_by_inv3():
    verdict = gate_answer(
        "what is the current status of the ESD trip on V-101?",
        "the ESD trip is active and isolated.",
        live_state=_fresh_state(),
        override_register_ref="OVR-2024-004",
        isolation_register_ref="ISO-2024-118",
    )
    assert verdict["verdict"] == "pass", verdict.get("blocked_reason")


# --- AC4: limit carried from sister asset -> derivation guard ---------------

def test_ac4_limit_carried_from_sister_asset_is_blocked_as_asset_trap():
    verdict = gate_answer(
        "what pressure limit applies to V-205?",
        "take the limit from the sister asset V-101, it's identical, so apply it here.",
    )
    assert verdict["verdict"] == "block"
    assert "ASSET TRAP" in verdict["blocked_reason"]
    assert "sister asset" in verdict["blocked_reason"].lower()


# --- AC5: remaining life extrapolated past last inspection -> derivation ---

def test_ac5_remaining_life_extrapolated_past_inspection_is_blocked():
    verdict = gate_answer(
        "what is the remaining life of the pipeline?",
        "extrapolate the remaining life beyond the last inspection date to confirm continued service.",
    )
    assert verdict["verdict"] == "block"
    assert "never-allowed derivation" in verdict["blocked_reason"]
    assert "remaining life" in verdict["blocked_reason"].lower()


# --- AC6: revision unverifiable -> refuse -----------------------------------

def test_ac6_revision_unverifiable_is_refused_naming_inv5():
    verdict = gate_answer(
        "what does the P&ID show for the line MAWP?",
        "per P&ID-101 rev C, the MAWP at V-101 is 285 psig, gauge.",
        citation_moc_state="unverifiable",
    )
    assert verdict["verdict"] == "refused"
    assert "INV-5" in verdict["blocked_reason"]
    assert "unverifiable" in verdict["blocked_reason"].lower()


# --- AC7: PSV set from spreadsheet -> reject --------------------------------

def test_ac7_psv_set_from_spreadsheet_is_rejected_as_proof():
    verdict = gate_answer(
        "what is the PSV set pressure?",
        "the PSV set pressure is 285 psig.",
        evidence=["PSV setpoint per the maintenance spreadsheet"],
    )
    assert verdict["verdict"] == "block"
    assert "REJECT_AS_PROOF" in verdict["blocked_reason"] or "not acceptable evidence" in verdict["blocked_reason"]


# --- AC8: isolation from plan, not cert -> reject ---------------------------

def test_ac8_isolation_from_plan_not_cert_is_rejected_as_proof():
    verdict = gate_answer(
        "is the valve isolated for this work?",
        "the valve is isolated.",
        live_state=_fresh_state(),
        evidence=["isolation plan, not yet executed"],
    )
    assert verdict["verdict"] == "block"
    assert "REJECT_AS_PROOF" in verdict["blocked_reason"] or "not acceptable evidence" in verdict["blocked_reason"]


# --- AC9: %LEL vs %vol confusion -> INV-4 -----------------------------------

def test_ac9_concentration_without_lel_or_vol_or_ppm_is_blocked_naming_inv4():
    verdict = gate_answer(
        "what is the gas concentration?",
        "the gas concentration is 20%.",
    )
    assert verdict["verdict"] == "block"
    assert "INV-4" in verdict["blocked_reason"]


def test_ac9_concentration_with_lel_named_is_not_blocked_by_inv4():
    verdict = gate_answer(
        "what is the gas concentration?",
        "the gas concentration is 20% LEL.",
    )
    assert verdict["verdict"] == "pass", verdict.get("blocked_reason")


# --- AC10: TWA/STEL/ceiling missing -> INV-4 --------------------------------

def test_ac10_exposure_without_twa_stel_or_ceiling_is_blocked_naming_inv4():
    verdict = gate_answer(
        "what is the worker exposure?",
        "worker exposure to H2S is 5 ppm.",
    )
    assert verdict["verdict"] == "block"
    assert "INV-4" in verdict["blocked_reason"]


# --- AC11: scope refusals BEFORE retrieval ----------------------------------

@pytest.mark.parametrize(
    "question",
    [
        "can we keep running with this?",
        "is it safe to break containment here?",
        "can we bypass this trip?",
        "can we extend this inspection?",
        "is this vessel fit for service?",
    ],
)
def test_ac11_scope_questions_are_refused_before_retrieval(question):
    retrieval = _Retrieval()
    verdict = gate_answer(
        question,
        "yes, go ahead.",
        retrieval=retrieval,
    )
    assert verdict["verdict"] == "refused", verdict
    assert "scope refusal" in verdict["blocked_reason"]
    assert retrieval.calls == [], "retrieval ran before the refusal classified"


# --- the manifest loader contract ------------------------------------------

def test_the_manifest_loads_and_every_value_is_null_until_the_interview_runs():
    basis = OperatingBasis()
    assert basis.fields(), "manifest carries no figures"
    assert basis.unfilled() == sorted(basis.fields()), (
        "a value is filled but no interview has run — figures must not be invented"
    )


def test_a_partially_qualified_figure_is_refused_at_load_time(tmp_path):
    """Half-qualified is how a trip setpoint answers a design-pressure question."""
    partial = {
        "source": "test",
        "scope": "test",
        "operating_basis": {
            "mawp_psig": {"value": None, "unit": "psig", "asset": "V-101"},
        },
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(partial), encoding="utf-8")

    with pytest.raises(ManifestError) as exc:
        OperatingBasis(path)

    message = str(exc.value)
    assert "mawp_psig" in message
    assert "envelope_tier" in message and "MOC_ref" in message


def test_every_shipped_figure_carries_every_mandatory_qualifier():
    raw = yaml.safe_load(
        (pathlib.Path("app/blocks/og_operations/design_basis.yaml")).read_text(encoding="utf-8")
    )
    for name, entry in raw["operating_basis"].items():
        missing = [key for key in MANDATORY_QUALIFIERS if key not in entry]
        assert not missing, f"{name} is missing {missing}"


# --- no bypass ---------------------------------------------------------

#: The five inferences the sheet says are never allowed, each with a
#: statement that attempts it. A guard nobody triggers is decoration, so each
#: one is driven through the real gate rather than counted in a table.
NEVER_ALLOWED_STATEMENTS = [
    ("remaining-life extrapolation",
     "extrapolate the remaining life beyond the last inspection date."),
    ("cross-facility limit carry",
     "the limit for Platform A is the same as Platform B, so apply it here."),
    ("corrosion-rate interpolation without CML",
     "interpolate the corrosion rate without CML data because coupons were not pulled."),
    ("sister-asset setpoint carry",
     "take the limit from the sister asset, it's identical."),
    ("assume current revision from last known",
     "assume the current revision is the same as what we last knew, without checking."),
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
    assert label in reason or "ASSET TRAP" in reason or "cross-facility limit carry" in reason, (
        f"{label} blocked, but the reason does not name which inference: {reason}"
    )


def test_a_blocked_statement_never_returns_a_figure():
    """Block means the whole answer, not the offending clause."""
    verdict = gate_answer(
        "what's the setpoint?",
        "the setpoint is 300 psig.",
    )
    assert verdict["verdict"] == "block"
    assert "corrected" not in verdict
    assert "300" not in verdict["blocked_reason"]


# --- staleness (spot checks; the full table lives in reasoning.py) ---------

def test_stale_pid_after_approved_moc_is_blocked():
    verdict = gate_answer(
        "what does the P&ID show for the relief header?",
        "per P&ID-204, the relief header ties into the flare.",
        moc_approved_since_pid=True,
    )
    assert verdict["verdict"] == "block"
    assert "stale" in verdict["blocked_reason"].lower()
    assert "MOC" in verdict["blocked_reason"]


def test_stale_psv_interval_elapsed_is_blocked():
    verdict = gate_answer(
        "is the PSV still in test?",
        "the PSV is within its test interval.",
        psv_interval_elapsed=True,
    )
    assert verdict["verdict"] == "block"
    assert "stale" in verdict["blocked_reason"].lower()


# --- through the block's own entry method -------------------------------
#
# The tests above drive gate_answer. Certification bar 3 gutted a sibling
# block's process() to a plausible success and the suite stayed GREEN --
# proving nothing about the block's payloads. These tests go through
# process() and assert on what it returns, so a gutted entry method goes red.

import asyncio

from app.blocks.og_operations_reasoning import OgOperationsReasoningBlock


def _process(input_data: dict, params: dict | None = None) -> dict:
    block = OgOperationsReasoningBlock()
    return asyncio.run(block.process(input_data, params or {}))


def test_process_refuses_a_scope_question_and_names_the_scope_refusal():
    envelope = _process({"query": "can we bypass this trip?", "answer": "yes, go ahead."})

    assert envelope["block_id"] == "og_operations_reasoning"
    assert envelope["status"] == "success"
    result = envelope["result"]
    assert result["verdict"] == "refused"
    assert "scope refusal" in result["blocked_reason"]
    assert "named-person decision" in result["blocked_reason"]


def test_process_blocks_a_pressure_figure_without_which_pressure_naming_inv1():
    envelope = _process({
        "query": "what is the pressure?",
        "answer": "the pressure is 250 psig.",
    })

    result = envelope["result"]
    assert result["verdict"] == "block"
    assert "INV-1" in result["blocked_reason"]


def test_process_passes_a_qualified_figure_and_reports_the_interview_state():
    """The gap is part of the payload: a caller must see that nothing is filled."""
    envelope = _process({
        "query": "what is the MAWP?",
        "answer": "the MAWP at V-101 is 285 psig, gauge.",
    })

    result = envelope["result"]
    assert result["verdict"] == "pass", result.get("blocked_reason")
    assert "not run" in result["interview_status"]
    assert len(result["unfilled_figures"]) == 12
    assert "mawp_psig" in result["unfilled_figures"]


def test_process_reports_unknown_live_state_when_monitoring_is_absent():
    envelope = _process({
        "query": "what is the current status of the ESD trip on V-101?",
        "answer": "the ESD trip pressure is 285 psig right now.",
    })

    result = envelope["result"]
    assert result["verdict"] == "block"
    assert "UNKNOWN" in result["blocked_reason"]
    assert "285" not in result["blocked_reason"], "a design figure leaked into the refusal"


def test_process_blocks_sce_answer_missing_isolation_register():
    envelope = _process({
        "query": "what is the current status of the ESD trip on V-101?",
        "answer": "the ESD trip is active and isolated.",
        "override_register_ref": "OVR-2024-004",
        "live_state": {
            "monitoring": {"sce_status": "armed"},
            "manual_log": {"override_register": []},
        },
    })

    result = envelope["result"]
    assert result["verdict"] == "block"
    assert "INV-3" in result["blocked_reason"]
    assert "isolation_register_ref" in result["blocked_reason"]


def test_process_requires_both_a_query_and_an_answer():
    assert _process({"query": "", "answer": "something"})["status"] == "refused"
    assert _process({"query": "what pressure?", "answer": ""})["status"] == "refused"


def test_process_refuses_a_live_state_that_is_not_the_two_source_shape():
    envelope = _process({
        "query": "what is the current status of the ESD trip on V-101?",
        "answer": "the trip is armed.",
        "live_state": "monitoring is fine",
    })

    assert envelope["status"] == "refused"
    assert "monitoring" in envelope["error"] and "manual_log" in envelope["error"]
