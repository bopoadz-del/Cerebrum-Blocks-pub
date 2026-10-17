"""ppm_licensing_resolver: donor refusal paths + licensing fold.

Donor: <private-repo> reasoning/ppm_resolver.py + licensing.py +
market_router.py + guard.py.
"""
from __future__ import annotations

import asyncio

import pytest

from app.blocks.ppm_licensing_resolver import (
    PPM_UAE,
    GuardError,
    PPMRefuse,
    PpmLicensingResolverBlock,
    combine_verdicts,
    guard_request,
)


def _run(coro):
    return asyncio.run(coro)


def _block():
    return PpmLicensingResolverBlock()


def test_guard_ksa_refused():
    with pytest.raises(GuardError) as excinfo:
        guard_request(market="ksa")
    assert excinfo.value.code == "market_unsupported"
    assert "KSA is unsupported" in excinfo.value.message


def test_guard_forbidden_source_refused():
    with pytest.raises(GuardError) as excinfo:
        guard_request(source_system="procore")
    assert excinfo.value.code == "construction_pm_out_of_scope"


def test_guard_construction_pm_refused():
    with pytest.raises(GuardError) as excinfo:
        guard_request(market="uae", construction_pm=True)
    assert excinfo.value.code == "construction_pm_out_of_scope"


def test_guard_uae_allowed():
    guard_request(market="uae", source_system="maximo")


def test_fold_fail_beats_unprovable_beats_pass():
    from app.blocks.ppm_licensing_resolver import Verdict
    assert combine_verdicts([Verdict.PASS, Verdict.FAIL]) is Verdict.FAIL
    assert combine_verdicts([Verdict.PASS, Verdict.UNPROVABLE]) is Verdict.UNPROVABLE
    assert combine_verdicts([Verdict.PASS]) is Verdict.PASS
    assert combine_verdicts([]) is Verdict.UNPROVABLE


def test_resolve_ppm_uae_fire_pump_ok():
    b = _block()
    r = _run(b.execute({"action": "resolve_ppm", "market": "uae", "asset_type": "fire_pump", "operator_sop": "Operator ABC Fire SOP v3"}))
    assert r["status"] == "ok"
    res = r["result"]
    assert res["task_id"] == "PPM-CD-FIRE-PUMP"
    assert res["statutory_duty"] == "STAT-FIRE"
    assert res["sop_present"] is True
    assert res["cadence_authoritative"] is False
    assert res["cadence_days"] is None
    assert res["status"] == "issued"
    assert res["evidence_class"] == "B"
    assert "estimated" in res["cadence_note"]


def test_resolve_ppm_sop_missing_refused():
    b = _block()
    r = _run(b.execute({"action": "resolve_ppm", "market": "uae", "asset_type": "fire_pump", "operator_sop": None}))
    assert r["status"] == "refused"
    assert r["error"] == "sop_missing"
    assert r["result"]["refused"] is True
    assert "never estimated" in r["result"]["message"]


def test_resolve_ppm_short_sop_refused():
    b = _block()
    r = _run(b.execute({"action": "resolve_ppm", "market": "uae", "asset_type": "fire_pump", "operator_sop": "x"}))
    assert r["status"] == "refused"
    assert r["error"] == "sop_missing"


def test_resolve_ppm_ksa_refused():
    b = _block()
    r = _run(b.execute({"action": "resolve_ppm", "market": "ksa", "asset_type": "fire_pump", "operator_sop": "Some Operator SOP v9"}))
    assert r["status"] == "refused"
    assert r["error"] == "market_unsupported"


def test_resolve_ppm_uae_unknown_asset_refused():
    b = _block()
    r = _run(b.execute({"action": "resolve_ppm", "market": "uae", "asset_type": "boiler", "operator_sop": "Some Operator SOP v9"}))
    assert r["status"] == "refused"
    assert r["error"] == "statutory_missing"


def test_resolve_ppm_authoritative_frequency_refused(monkeypatch):
    b = _block()
    pack = dict(PPM_UAE)
    pack["authoritative_frequencies"] = True
    monkeypatch.setattr(b.ppm.router, "ppm_pack", lambda market: pack)
    r = _run(b.execute({"action": "resolve_ppm", "market": "uae", "asset_type": "fire_pump", "operator_sop": "Some Operator SOP v9"}))
    assert r["status"] == "refused"
    assert r["error"] == "generic_frequency_refused"


def test_resolve_ppm_generic_elevator_uses_legacy_task_id():
    b = _block()
    # Donor parity: the generic pack's duties carry no legacy_task_id, so the
    # fallback task id is PPM-<ASSET>.
    r = _run(b.execute({"action": "resolve_ppm", "market": "generic", "asset_type": "elevator", "operator_sop": "Generic Operator Lift SOP"}))
    assert r["status"] == "ok"
    assert r["result"]["task_id"] == "PPM-ELEVATOR"
    assert r["result"]["statutory_duty"] == "STAT-LIFT"


def test_resolve_ppm_dubai_normalizes_to_uae():
    b = _block()
    r = _run(b.execute({"action": "resolve_ppm", "market": "dubai", "asset_type": "elevator", "operator_sop": "Dubai Operator Lift SOP"}))
    assert r["status"] == "ok"
    assert r["result"]["market"] == "uae"


def test_guard_action_refuses_procore():
    b = _block()
    r = _run(b.execute({"action": "guard", "market": "uae", "source_system": "aconex"}))
    assert r["status"] == "refused"
    assert r["error"] == "construction_pm_out_of_scope"


def test_normalize_market():
    b = _block()
    assert _run(b.execute({"action": "normalize_market", "market": "abu_dhabi"}))["result"]["code"] == "uae"
    assert _run(b.execute({"action": "normalize_market", "market": "generic"}))["result"]["code"] == "generic"
    r = _run(b.execute({"action": "normalize_market", "market": "egypt"}))
    assert r["status"] == "refused"
    assert r["error"] == "market_unsupported"


def test_evaluate_licensing_all_pass():
    b = _block()
    from app.blocks.ppm_licensing_resolver import LICENSING_UAE, PREREQ_UAE
    all_ids = {lic["id"] for lic in LICENSING_UAE["licenses"]}
    prereq_ids = {item for items in PREREQ_UAE["maps"].values() for item in items}
    satisfied = {k: "PASS" for k in all_ids | prereq_ids}
    r = _run(b.execute({"action": "evaluate_licensing", "market": "uae", "satisfied": satisfied}))
    assert r["status"] == "ok"
    res = r["result"]
    assert res["overall"] == "PASS"
    assert res["master_pacer"]["license_id"] is None
    assert res["soft_opening_blocked"] is False
    assert res["evidence_class"] == "B"


def test_evaluate_licensing_empty_satisfied_unprovable():
    b = _block()
    r = _run(b.execute({"action": "evaluate_licensing", "market": "uae", "satisfied": {}}))
    assert r["status"] == "ok"
    res = r["result"]
    assert res["overall"] == "UNPROVABLE"
    cd = next(row for row in res["licenses"] if row["id"] == "UAE-CD")
    assert cd["verdict"] == "UNPROVABLE"
    assert len(cd["missing_prerequisites"]) == 6
    assert res["master_pacer"]["license_id"] == "UAE-CD"
    assert res["master_pacer"]["kind"] == "fire_cd"
    assert res["master_pacer"]["method"] == "computed_from_prerequisite_graph"


def test_evaluate_licensing_fail_beats_pass():
    b = _block()
    satisfied = {"UAE-DED": "PASS", "UAE-EJARI": "PASS", "UAE-UTIL": "FAIL", "UAE-ISP": "PASS", "UAE-CCTV": "PASS"}
    r = _run(b.execute({"action": "evaluate_licensing", "market": "uae", "satisfied": satisfied}))
    res = r["result"]
    row = next(x for x in res["licenses"] if x["id"] == "UAE-UTIL")
    assert row["verdict"] == "FAIL"
    assert res["overall"] == "FAIL"


def test_evaluate_licensing_pacer_dtcm_when_fire_passes():
    b = _block()
    # Fire chain fully satisfied; UAE-ISP omitted so UAE-DTCM is UNPROVABLE
    # and becomes the computed master pacer.
    satisfied = {
        "UAE-DED": "PASS",
        "UAE-EJARI": "PASS",
        "UAE-UTIL": "PASS",
        "UAE-CCTV": "PASS",
        "UAE-CD": "PASS",
        "fire_pump_class_a": "PASS",
        "fire_alarm_cx": "PASS",
        "emergency_lighting_cx": "PASS",
    }
    r = _run(b.execute({"action": "evaluate_licensing", "market": "uae", "satisfied": satisfied}))
    res = r["result"]
    assert res["master_pacer"]["license_id"] == "UAE-DTCM"
    assert res["master_pacer"]["kind"] == "licensing_path"
    assert res["soft_opening_blocked"] is True


def test_evaluate_licensing_generic():
    b = _block()
    r = _run(b.execute({"action": "evaluate_licensing", "market": "generic", "satisfied": {}}))
    assert r["status"] == "ok"
    assert r["result"]["market"] == "generic"
    fire = next(row for row in r["result"]["licenses"] if row["id"] == "GEN-FIRE")
    assert fire["missing_prerequisites"] == ["GEN-TRADE", "GEN-UTIL", "GEN-CCTV", "fire_pump_class_a_or_b"]


def test_evaluate_licensing_invalid_verdict_errors_not_crashes():
    b = _block()
    r = _run(b.execute({"action": "evaluate_licensing", "market": "uae", "satisfied": {"UAE-DED": "MAYBE"}}))
    assert r["status"] == "error"


def test_evaluate_licensing_ksa_refused():
    b = _block()
    r = _run(b.execute({"action": "evaluate_licensing", "market": "saudi_arabia", "satisfied": {}}))
    assert r["status"] == "refused"
    assert r["error"] == "market_unsupported"


def test_unknown_action_error():
    b = _block()
    r = _run(b.execute({"action": "estimate_frequency"}))
    assert r["status"] == "error"
    assert "unknown action" in r["error"]


@pytest.mark.asyncio
async def test_process_is_async_coroutine():
    b = _block()
    r = await b.process({"action": "resolve_ppm", "market": "uae", "asset_type": "domestic_water", "operator_sop": "Water Hygiene SOP Rev 4"})
    assert r["status"] == "ok"
    assert r["result"]["statutory_duty"] == "STAT-WATER"
