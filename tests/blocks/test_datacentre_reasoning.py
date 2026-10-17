"""Data centre reasoning layer — acceptance criteria AC1–AC14 + the chiller
incident regression. Written BEFORE the implementation (fail-first)."""
from __future__ import annotations

import pathlib
import re
import time

import pytest

from app.blocks.datacentre.reasoning import (
    DesignBasis,
    ResilienceState,
    gate_answer,
)


# --- shared fixtures -------------------------------------------------------

def _fresh_state() -> ResilienceState:
    now = time.time()
    return ResilienceState(
        bms={"chillers": "ok", "pumps": "ok", "ups": "ok", "generator": "ok"},
        manual_log={"isolations": [], "bypasses": [], "components_out": []},
        fetched_at=now,
    )


def _retrieval_counter():
    calls = []

    def retrieve(query: str):
        calls.append(query)
        return []

    return retrieve, calls


# --- AC1 -------------------------------------------------------------------

def test_ac1_tested_requires_level_load_and_scenario():
    _, calls = _retrieval_counter()
    v = gate_answer(
        "what was the result of the chiller test?",
        "the chiller was tested and passed.",
        live_state=_fresh_state(),
        retrieval=calls,
    )
    assert v["verdict"] == "block"
    assert "INV-1" in v["blocked_reason"]


# --- AC2 -------------------------------------------------------------------

def test_ac2_resilience_requires_basis():
    v = gate_answer(
        "are we N+1 right now?",
        "yes, the facility is N+1.",
        live_state=_fresh_state(),
    )
    assert v["verdict"] == "block"
    assert "INV-2" in v["blocked_reason"]


# --- AC3 -------------------------------------------------------------------

def test_ac3_as_currently_operating_with_chiller_out_reports_N():
    state = ResilienceState(
        bms={"chillers": "chiller-2 offline"},
        manual_log={
            "isolations": [],
            "bypasses": [],
            "components_out": [{"component": "chiller-2", "since": time.time() - 3600}],
        },
        fetched_at=time.time(),
    )
    v = gate_answer(
        "are we N+1?",
        "yes, the facility is N+1.",
        live_state=state,
        basis="as_currently_operating",
    )
    assert v["verdict"] == "pass"
    assert v["corrected"]["redundancy"] == "N"
    assert "chiller-2" in v["corrected"]["degraded_component"]
    assert v["corrected"]["time_in_degraded_seconds"] >= 3600


# --- AC4 -------------------------------------------------------------------

def test_ac4_capacity_requires_redundancy_basis():
    v = gate_answer(
        "how much capacity is available?",
        "available capacity is 500 kW.",
        live_state=_fresh_state(),
    )
    assert v["verdict"] == "block"
    assert "INV-3" in v["blocked_reason"]


# --- AC5 -------------------------------------------------------------------

def test_ac5_ready_for_it_load_refused_before_retrieval():
    retrieve, calls = _retrieval_counter()
    v = gate_answer(
        "is the facility ready for IT load?",
        "yes.",
        live_state=_fresh_state(),
        retrieval=retrieve,
    )
    assert v["verdict"] == "refused"
    assert calls == [], "INV-4 must refuse BEFORE retrieval"


# --- AC6 -------------------------------------------------------------------

def test_ac6_ride_through_from_passed_l4_blocked():
    v = gate_answer(
        "will it ride through a power failure?",
        "yes — the chiller system passed the L4 functional test.",
        live_state=_fresh_state(),
        evidence=["passed L4 functional test"],
    )
    assert v["verdict"] == "block"
    assert "ride_through" in v["blocked_reason"]


# --- AC7 -------------------------------------------------------------------

def test_ac7_partial_to_full_extrapolation_blocked():
    v = gate_answer(
        "what performance can we expect at design load?",
        "at design load the cooling holds 22 C, measured at day-one load (25%).",
        live_state=_fresh_state(),
    )
    assert v["verdict"] == "block"
    assert "partial" in v["blocked_reason"] and "full" in v["blocked_reason"]


# --- AC8 -------------------------------------------------------------------

def test_ac8_bms_unreachable_states_unknown_never_design_basis():
    v = gate_answer(
        "what is the current resilience?",
        "the facility is N+1 with 30 minutes UPS autonomy.",
        live_state=None,
    )
    assert v["verdict"] == "block"
    assert "unknown" in v["blocked_reason"].lower()
    assert "0.7" not in v["blocked_reason"]
    assert "N+1" not in v["blocked_reason"]


# --- AC9 -------------------------------------------------------------------

def test_ac9_stale_manual_log_blocks():
    state = ResilienceState(
        bms={"chillers": "ok"},
        manual_log={"components_out": []},
        fetched_at=time.time() - 10_000_000,
    )
    v = gate_answer(
        "what redundancy do we have?",
        "N+1.",
        live_state=state,
        basis="as_currently_operating",
    )
    assert v["verdict"] == "block"
    assert "both required" in v["blocked_reason"]


# --- AC10 ------------------------------------------------------------------

def test_ac10_tier_design_certificate_blocked_for_constructed():
    v = gate_answer(
        "is the facility tier-certified as constructed?",
        "yes — here is the Tier design certification.",
        live_state=_fresh_state(),
        evidence=["tier design certificate"],
    )
    assert v["verdict"] == "block"
    assert "design certificate" in v["blocked_reason"].lower() or "constructed" in v["blocked_reason"].lower()


# --- AC11 ------------------------------------------------------------------

def test_ac11_one_bad_figure_blocks_the_whole_answer():
    v = gate_answer(
        "summarise the facility",
        "load is 0.7 MW, PUE is 1.4, and the facility is N+1.",
        live_state=_fresh_state(),
    )
    assert v["verdict"] == "block"
    assert "INV-2" in v["blocked_reason"]


# --- AC12 ------------------------------------------------------------------

def test_ac12_every_answer_path_routes_through_invariant_evaluation():
    src = pathlib.Path("app/blocks/datacentre/reasoning.py").read_text(encoding="utf-8")
    # The single public entry is gate_answer; every verdict it can emit is
    # produced through the invariant pipeline — no early return skips it.
    body = src[src.index("def gate_answer"):]
    early_returns = re.findall(r"return \{[\"']verdict[\"']", body)
    assert len(early_returns) <= 1, "verdict returns must route through one evaluation path"
    assert "_evaluate_invariants" in src


# --- AC13 ------------------------------------------------------------------

def test_ac13_deterministic_verdicts():
    state = _fresh_state()
    results = set()
    for _ in range(5):
        v = gate_answer(
            "are we N+1?",
            "yes, the facility is N+1.",
            live_state=state,
        )
        results.add((v["verdict"], v.get("blocked_reason", "")))
    assert len(results) == 1


# --- AC14 ------------------------------------------------------------------

def test_ac14_verdicts_without_network_or_credentials():
    import os

    old = {}
    for key in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "KIMI_API_KEY"):
        old[key] = os.environ.pop(key, None)
    try:
        v = gate_answer(
            "are we N+1?",
            "yes, the facility is N+1.",
            live_state=_fresh_state(),
        )
        assert v["verdict"] == "block"
        assert "INV-2" in v["blocked_reason"]
    finally:
        for key, value in old.items():
            if value is not None:
                os.environ[key] = value


# --- chiller incident regression ------------------------------------------

def test_chiller_incident_pump_sequence_regression():
    # The sheet's real incident: chiller failure at IST; temperature rose
    # faster than expected due to pump sequence time delay; the control
    # sequence was re-modified and retested.
    # 1) A claim citing the PRE-correction test as proof of current
    #    behaviour must block: the IST result is stale after modification.
    v1 = gate_answer(
        "how fast does temperature rise on chiller failure?",
        "the IST result from before the control change still applies.",
        live_state=_fresh_state(),
        evidence=["IST result"],
        test_modified_since_ist=True,
    )
    assert v1["verdict"] == "block"
    assert "stale" in v1["blocked_reason"].lower()
    # 2) The corrected, retested sequence is citable.
    v2 = gate_answer(
        "how fast does temperature rise on chiller failure?",
        "per the retested control sequence, rise is within limits.",
        live_state=_fresh_state(),
        evidence=["retested control sequence (post-modification)"],
    )
    assert v2["verdict"] == "pass"
