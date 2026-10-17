"""<private-repo> scorer + hotelops evidence classifier tests."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.answer_quality_scorer import AnswerQualityScorerBlock, is_status_line, looks_truncated
from app.blocks.evidence_classifier import EvidenceClassifierBlock, classify_evidence


def _run(coro):
    return asyncio.run(coro)


def test_status_line_detected():
    assert is_status_line("Processing your request…") is True
    assert is_status_line("Checking the manual. The torque is 38 Nm.") is False


def test_truncation_detected():
    assert looks_truncated("The final torque value is 38 Nm, and the bolt") is True
    assert looks_truncated("The final torque value is 38 Nm...") is False


def test_score_status_line_fails():
    b = AnswerQualityScorerBlock()
    r = _run(b.process({"action": "score", "answered": True, "response": "Analysis complete."}))
    assert r["result"]["verdict"] == "fail"
    assert r["result"]["failure_class"] == "silent_failure"


def test_score_real_answer_passes():
    b = AnswerQualityScorerBlock()
    r = _run(b.process({"action": "score", "answered": True, "response": "The pump duty point is 38 kW at 750 RPM with a 12% safety margin."}))
    assert r["result"]["verdict"] == "pass"


def test_score_scaffolding_leak_fails():
    b = AnswerQualityScorerBlock()
    r = _run(b.process({"action": "score", "answered": True, "response": "The answer is 42. <tool_call>compute()</tool_call>"}))
    assert r["result"]["verdict"] == "fail"


def test_fire_pump_test_line_to_tank_fails():
    r = classify_evidence({"asset_type": "fire_pump", "test_line_to_tank": True, "documents": []})
    assert r["verdict"] == "FAIL"
    assert "INV-FIRE-PUMP-TEST-TO-TANK" in r["invalidity_ids"]


def test_fire_pump_serial_mismatch_fails():
    r = classify_evidence({"asset_type": "fire_pump", "serial_on_certificate": "S1", "serial_on_register": "S2", "documents": []})
    assert r["verdict"] == "FAIL"
    assert "INV-FIRE-PUMP-SERIAL-MISMATCH" in r["invalidity_ids"]


def test_fire_pump_class_a_pass():
    r = classify_evidence({
        "asset_type": "fire_pump",
        "documents": ["as_built_drawing", "witnessed_commissioning_sheet", "nameplate_photo_unobstructed", "serial_on_asset_register"],
        "serial_on_certificate": "S1",
        "serial_on_register": "S1",
        "nameplate_readable": True,
        "test_line_to_tank": False,
        "covers_clips_removed": True,
        "test_age_days": 30,
        "site_witness": True,
    })
    assert r["evidence_class"] == "A"
    assert r["verdict"] == "PASS"


def test_unknown_asset_type_unprovable():
    r = classify_evidence({"asset_type": "spaceship"})
    assert r["verdict"] == "UNPROVABLE"


def test_fls_unit_not_integrated_unprovable():
    r = classify_evidence({"asset_type": "fire_life_safety", "individual_tests_pass": True, "integrated_interface_test": False})
    assert r["verdict"] == "UNPROVABLE"
    assert "INV-CE-UNIT-NOT-INTEGRATED" in r["invalidity_ids"]
