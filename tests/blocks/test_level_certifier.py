"""Level certifier tests - ported behavior from <private-repo> gates/independence/canary."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.level_certifier import (
    LevelCertifierBlock,
    TrustTier,
    GateConfig,
    GraderIdentity,
    GraderKind,
    TargetFingerprint,
    mint,
    find,
    scan_for_any,
    refusal_reason,
)


def _run(coro):
    return asyncio.run(coro)


def _gate(payload):
    b = LevelCertifierBlock()
    return _run(b.process({"action": "gate", **payload}))


# --- gate math (gates.py) --------------------------------------------------

def test_exact_95_percent_certifies():
    r = _gate({"counted_pass": 19, "counted_total": 20, "trap_pass": 0, "trap_total": 0,
               "sev1_count": 0, "unscored": 0})
    assert r["status"] == "ok"
    assert r["result"]["gate"]["tier"] == "certified"


def test_946_percent_is_not_95_the_fraction_trap():
    # 946/1000 = 94.6% - displayed as 95% is how a target certifies without
    # meeting the gate, so the comparison is exact-fraction, never rounded.
    r = _gate({"counted_pass": 946, "counted_total": 1000, "trap_pass": 0, "trap_total": 0,
               "sev1_count": 0, "unscored": 0})
    assert r["result"]["gate"]["tier"] == "not_certified"
    core = next(c for c in r["result"]["gate"]["checks"] if c["name"] == "core_pass_rate")
    assert core["met"] is False


def test_one_sprung_trap_fails_even_at_full_core():
    r = _gate({"counted_pass": 20, "counted_total": 20, "trap_pass": 0, "trap_total": 1,
               "sev1_count": 0, "unscored": 0})
    assert r["result"]["gate"]["tier"] == "not_certified"
    trap = next(c for c in r["result"]["gate"]["checks"] if c["name"] == "trap_pass_rate")
    assert trap["met"] is False


def test_waiver_is_provisional_never_certified():
    r = _gate({"counted_pass": 18, "counted_total": 20, "trap_pass": 0, "trap_total": 0,
               "sev1_count": 0, "unscored": 0,
               "config": {"waived": ["core_pass_rate"]}})
    assert r["result"]["gate"]["tier"] == "provisional"
    assert "waived by the operator" in r["result"]["gate"]["reason"]


def test_contaminated_run_is_void_not_failed():
    r = _gate({"counted_pass": 20, "counted_total": 20, "trap_pass": 0, "trap_total": 0,
               "sev1_count": 0, "unscored": 0, "contaminated": True})
    assert r["result"]["gate"]["tier"] == "void"
    assert "contaminated" in r["result"]["gate"]["reason"]


def test_unscored_question_blocks_certification():
    r = _gate({"counted_pass": 20, "counted_total": 20, "trap_pass": 0, "trap_total": 0,
               "sev1_count": 0, "unscored": 1})
    assert r["result"]["gate"]["tier"] == "not_certified"


def test_gate_without_counted_total_is_refused():
    r = _gate({"counted_pass": 19})
    assert r["status"] == "refused"


def test_gateconfig_from_dict_never_goes_through_a_float():
    cfg = GateConfig.from_dict({"core_pass_rate": "0.95"})
    assert cfg.core_pass_rate.numerator == 19 and cfg.core_pass_rate.denominator == 20


# --- independence (independence.py) ----------------------------------------

def test_self_grading_is_refused_not_warned():
    b = LevelCertifierBlock()
    r = _run(b.process({
        "action": "independence",
        "grader": {"kind": "llm_judge", "identity": "openai:gpt-4o:2024-05-13"},
        "target": {"provider": "openai", "model": "gpt-4o", "version": "2024-05-13"},
    }))
    assert r["status"] == "refused"
    assert "Self-grading" in r["error"]


def test_independent_grader_proceeds():
    b = LevelCertifierBlock()
    r = _run(b.process({
        "action": "independence",
        "grader": {"kind": "deterministic", "identity": "level:deterministic-scorers:v1"},
        "target": {"provider": "openai", "model": "gpt-4o", "version": "2024-05-13"},
    }))
    assert r["status"] == "ok"
    assert r["result"]["independent"] is True


def test_identity_comparison_is_case_and_space_insensitive():
    grader = GraderIdentity(kind=GraderKind.DETERMINISTIC, identity=" OPENAI:GPT-4O:V1 ")
    target = TargetFingerprint(provider="openai", model="gpt-4o", version="v1")
    assert grader.is_independent_of(target) is False
    assert refusal_reason(grader, target) is not None


def test_grader_without_identity_is_refused():
    b = LevelCertifierBlock()
    r = _run(b.process({"action": "independence", "grader": {"kind": "llm_judge"},
                        "target": {"provider": "x", "model": "y"}}))
    assert r["status"] == "refused"
    assert "identity" in r["error"]


def test_target_without_provider_or_model_is_refused():
    b = LevelCertifierBlock()
    r = _run(b.process({"action": "independence",
                        "grader": {"identity": "level:deterministic-scorers:v1"},
                        "target": {"model": "y"}}))
    assert r["status"] == "refused"
    assert "provider" in r["error"]


# --- canary (canary.py) ----------------------------------------------------

def test_mint_is_content_stable_not_random():
    a = mint("battery-1", "token-xyz")
    b2 = mint("battery-1", "token-xyz")
    assert a == b2 == "LVL-CANARY-BATTERY1-TOKENXYZ"


def test_mint_refuses_too_short_material():
    b = LevelCertifierBlock()
    r = _run(b.process({"action": "mint_canary", "battery_id": "ab", "token": "tok1"}))
    assert r["status"] == "refused"
    r2 = _run(b.process({"action": "mint_canary", "battery_id": "batt-1", "token": "tk"}))
    assert r2["status"] == "refused"


def test_find_is_case_insensitive_and_scan_catches_foreign_batteries():
    canary = mint("battery-1", "token-xyz")
    assert find("the answer is " + canary.lower(), [canary]) == (canary,)
    assert find("nothing here", [canary]) == ()
    foreign = "LVL-CANARY-ABCDEF12-XYZ987654321"
    assert scan_for_any("trained on " + foreign) == (foreign,)


def test_scan_action_marks_contamination():
    b = LevelCertifierBlock()
    canary = mint("battery-1", "token-xyz")
    r = _run(b.process({"action": "scan_canary", "text": "output contains " + canary,
                        "canaries": [canary]}))
    assert r["status"] == "ok"
    assert r["result"]["contaminated"] is True
    assert "void" in r["result"]["note"]


def test_scan_without_hits_is_clean():
    b = LevelCertifierBlock()
    r = _run(b.process({"action": "scan_canary", "text": "ordinary answer",
                        "canaries": [mint("battery-1", "token-xyz")]}))
    assert r["result"]["contaminated"] is False


# --- taxonomy --------------------------------------------------------------

def test_taxonomy_lists_eleven_classes_and_silent_classes():
    b = LevelCertifierBlock()
    r = _run(b.process({"action": "taxonomy"}))
    assert r["status"] == "ok"
    assert len(r["result"]["classes"]) == 11
    assert r["result"]["silent_classes"] == [
        "fabricated_figure", "silent_failure", "trap_failure", "wrong_source_contamination",
    ]


def test_unknown_action_is_error():
    b = LevelCertifierBlock()
    r = _run(b.process({"action": "nonsense"}))
    assert r["status"] == "error"
    assert r["block_id"] == "level_certifier"
