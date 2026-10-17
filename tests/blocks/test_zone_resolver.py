"""Zone resolver tests - ported behavior from <private-repo> ZoneResolver."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.zone_resolver import ZoneResolverBlock, as_vector3, _box_gap, _magnitude


def _run(coro):
    return asyncio.run(coro)


ELEMENTS = {
    "g1": {"discipline": "mechanical", "is_gravity": False, "bbox": [0.0, 0.0, 0.0, 0.2, 0.2, 0.2]},
    "g2": {"discipline": "mechanical", "is_gravity": False, "bbox": [0.0, 0.0, 0.5, 0.2, 0.2, 0.7]},
    "g3": {"discipline": "structural", "is_gravity": False, "bbox": [0.0, 0.0, 0.0, 0.2, 0.2, 0.2]},
}

CLASH = {
    "id": "c1",
    "clash_key": "CK1",
    "kind": "clearance",
    "rule_id": "r1",
    "required_gap_mm": 400,
    "owner": "zone",
    "a_gid": "g1",
    "b_gid": "g2",
    "zone_gids": ["g1"],
    "systems": ["duct", "cable"],
    "severity_mm": 10.0,
}

PASS = {"passed": True, "reason": "clear"}
UNPROVABLE = {"passed": True, "reason": "model could not answer", "unprovable": True}
BOUNDARY_FAIL = {"passed": False, "reason": "move lands in a neighbouring zone"}
GEOMETRY_FAIL = {"passed": False, "reason": "still inside the required gap"}


def _cand(vector, monitors=None):
    return {"move_type": "translate", "vector_mm": vector,
            "monitors": monitors or {"geometry": PASS, "boundary": PASS, "integrity": PASS}}


_SENTINEL = object()


def _resolve(clash=_SENTINEL, candidates=None, **kw):
    b = kw.pop("block", None) or ZoneResolverBlock()
    if clash is _SENTINEL:
        clash = {}
    payload = {
        "action": "resolve",
        "clash": None if clash is None else dict(CLASH, **clash),
        "candidates": candidates,
        "elements": ELEMENTS,
        "zone_key": "z1",
    }
    payload.update(kw)
    return b, _run(b.process(payload))


def test_clean_sweep_commits_verified():
    b, r = _resolve(candidates=[_cand([0, 0, -500])])
    assert r["status"] == "ok"
    assert r["result"]["verdict"] == "verified"
    assert r["result"]["committed_as"] == "z1:g1:CK1"
    committed = _run(b.process({"action": "committed"}))
    assert committed["result"]["count"] == 1


def test_unprovable_check_is_verified_conditional_never_verified():
    b, r = _resolve(candidates=[
        _cand([0, 0, -500], {"geometry": PASS, "boundary": PASS, "integrity": UNPROVABLE}),
    ])
    assert r["result"]["verdict"] == "verified_conditional"
    assert r["result"]["unprovable_checks"] == ["integrity"]
    assert r["result"]["committed_as"] == "z1:g1:CK1"


def test_boundary_owned_clash_is_handed_to_coordinator_never_committed():
    b, r = _resolve(
        clash={"owner": "coordinator"}, candidates=[_cand([0, 0, -500])],
    )
    assert r["result"]["handed_to_coordinator"] is True
    assert r["result"]["committed_as"] is None
    committed = _run(b.process({"action": "committed"}))
    assert committed["result"]["count"] == 0


def test_rejected_axis_is_blocked_for_further_attempts():
    b, r = _resolve(candidates=[
        _cand([0, 0, -500], {"geometry": PASS, "boundary": BOUNDARY_FAIL, "integrity": PASS}),
        _cand([0, 0, -900], {"geometry": PASS, "boundary": PASS, "integrity": PASS}),
        _cand([0, -500, 0]),
    ])
    # Attempt 1 rejected on the -z heading; attempt 2 would push the same
    # heading harder, so it is skipped; attempt 3 on the -y heading commits.
    assert r["result"]["verdict"] == "verified"
    assert r["result"]["attempt"] == 2
    assert len(r["result"]["rejected_attempts"]) == 1
    assert r["result"]["alternatives"][0]["objections"] == {"boundary": "move lands in a neighbouring zone"}


def test_three_monitored_failures_escalate_with_named_objections():
    b, r = _resolve(candidates=[
        _cand([0, 0, -500], {"geometry": PASS, "boundary": BOUNDARY_FAIL, "integrity": PASS}),
        _cand([0, -500, 0], {"geometry": GEOMETRY_FAIL, "boundary": PASS, "integrity": PASS}),
        _cand([-500, 0, 0], {"geometry": GEOMETRY_FAIL, "boundary": PASS, "integrity": PASS}),
    ])
    assert r["result"]["verdict"] == "escalated"
    assert len(r["result"]["alternatives"]) == 3
    assert {tuple(sorted(o["objections"])) for o in r["result"]["alternatives"]} == {("boundary",), ("geometry",)}


def test_clearance_without_rule_is_flagged_never_dressed_up():
    b, r = _resolve(
        clash={"kind": "clearance", "rule_id": None}, candidates=[_cand([0, 0, -500])],
    )
    assert r["result"]["verdict"] == "flagged_unsourced"
    assert "no sourced rule" in r["result"]["alternatives"][0]["reason"]


def test_missing_monitor_verdict_is_refused():
    b, r = _resolve(candidates=[
        {"move_type": "translate", "vector_mm": [0, 0, -500],
         "monitors": {"geometry": PASS, "boundary": PASS}},
    ])
    assert r["status"] == "refused"
    assert "integrity" in r["error"]


def test_candidate_without_any_monitors_is_refused():
    b, r = _resolve(candidates=[{"move_type": "translate", "vector_mm": [0, 0, -500]}])
    assert r["status"] == "refused"


def test_vector_that_is_not_three_numbers_is_refused():
    b, r = _resolve(candidates=[{"move_type": "translate", "vector_mm": [0, -500]}])
    assert r["status"] == "refused"
    assert "three numbers" in r["error"]


def test_resolve_without_clash_is_refused():
    b, r = _resolve(clash=None, candidates=[])
    assert r["status"] == "refused"


def test_clash_without_id_is_refused():
    b, r = _resolve(clash={"id": None, "clash_key": None}, candidates=[])
    assert r["status"] == "refused"


def test_unknown_owner_is_refused():
    b, r = _resolve(clash={"owner": "someone"}, candidates=[_cand([0, 0, -500])])
    assert r["status"] == "refused"


def test_structural_element_is_never_the_one_moved():
    b = ZoneResolverBlock()
    clash = dict(CLASH, **{"a_gid": "g3", "zone_gids": ["g1"]})
    r = _run(b.process({
        "action": "resolve", "clash": clash,
        "candidates": [_cand([0, 0, -500])], "elements": ELEMENTS,
    }))
    # g3 is structural in the fixture, so the movable element is g1's partner.
    assert r["result"]["element_gid"] != "g3"
    assert r["result"]["verdict"] == "verified"


def test_rank_candidates_puts_achieving_move_first():
    b = ZoneResolverBlock()
    ranked = b._rank_candidates(
        [{"move_type": "t", "vector_mm": [0, 0, -50]}, {"move_type": "t", "vector_mm": [0, 0, -500]}],
        ELEMENTS["g1"]["bbox"], ELEMENTS["g2"]["bbox"], [], 400,
    )
    # The -500 move achieves the 400 mm gap; the -50 move cannot.
    assert ranked[0]["vector_mm"] == [0, 0, -500]


def test_box_gap_and_vector_helpers():
    assert _box_gap([0, 0, 0, 1, 1, 1], [2, 0, 0, 3, 1, 1]) == 1.0
    assert _box_gap([0, 0, 0, 1, 1, 1], [0.5, 0.5, 0.5, 2, 2, 2]) == 0.0
    assert as_vector3([1, 2, 3]) == (1.0, 2.0, 3.0)
    assert _magnitude([3, 4, 0]) == 5.0


def test_run_orders_by_kit_rank_then_worst_first_and_tallies():
    b = ZoneResolverBlock()
    clash_a = dict(CLASH, id="ca", clash_key="CK-A", systems=["duct"], severity_mm=5.0)
    clash_b = dict(CLASH, id="cb", clash_key="CK-B", systems=["cable"], severity_mm=50.0)
    r = _run(b.process({
        "action": "run",
        "clashes": [clash_b, clash_a],  # arrival order reversed
        "order": ["duct", "cable"],
        "candidates": [_cand([0, 0, -500])],
        "elements": ELEMENTS,
    }))
    assert r["status"] == "ok"
    assert [o["clash_id"] for o in r["result"]["outcomes"]] == ["ca", "cb"]
    assert r["result"]["clashes_seen"] == 2
    assert r["result"]["verified"] == 2


def test_run_with_no_usable_payload_refuses_on_first_clash():
    b = ZoneResolverBlock()
    r = _run(b.process({
        "action": "run",
        "clashes": [dict(CLASH)],
        "candidates": [{"move_type": "t", "vector_mm": [0, 0]}],
        "elements": ELEMENTS,
    }))
    assert r["status"] == "refused"


def test_unknown_action_is_error():
    b = ZoneResolverBlock()
    r = _run(b.process({"action": "nonsense"}))
    assert r["status"] == "error"
    assert r["block_id"] == "zone_resolver"
