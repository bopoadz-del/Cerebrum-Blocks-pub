"""MEP review ledger â€” ported <private-repo> review.py + review_package.py
+ monitors/base.py (three-valued verdict discipline, in-process ledger)."""
from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

from app.blocks.mep_review_ledger import MepReviewLedgerBlock


def _run(coro):
    return asyncio.run(coro)


def _p(b, payload):
    return _run(b.process(payload))


# -- three-valued monitor contract (monitors/base.py) --------------------------

def _res(monitor, verdict, checks=None):
    return {"monitor": monitor, "verdict": verdict, "reason": "", "checks": checks or []}


def test_aggregate_fail_dominates_conditional_and_pass():
    b = MepReviewLedgerBlock()
    r = _p(b, {"action": "aggregate", "results": [
        _res("boundary", "fail"),
        _res("geometry", "pass"),
        _res("integrity", "conditional"),
    ]})
    assert r["status"] == "ok"
    assert r["result"]["verdict"] == "fail"


def test_aggregate_conditional_is_not_pass():
    b = MepReviewLedgerBlock()
    r = _p(b, {"action": "aggregate", "results": [
        _res("boundary", "pass"),
        _res("integrity", "conditional"),
    ]})
    assert r["result"]["verdict"] == "conditional"


def test_aggregate_pass_requires_every_monitor_full_pass():
    b = MepReviewLedgerBlock()
    r = _p(b, {"action": "aggregate", "results": [_res("a", "pass"), _res("b", "pass")]})
    assert r["result"]["verdict"] == "pass"


def test_unprovable_across_names_monitor_check():
    b = MepReviewLedgerBlock()
    r = _p(b, {"action": "unprovable_across", "results": [
        _res("boundary", "conditional", checks=[
            {"name": "ports", "status": "unprovable", "detail": "no ports"},
            {"name": "borders", "status": "pass", "detail": ""},
        ]),
    ]})
    assert r["result"]["unprovable_checks"] == ["boundary.ports"]


# -- review decisions (review.py apply_review discipline) -----------------------

def test_approve_refuses_unacknowledged_unprovable_checks():
    b = MepReviewLedgerBlock()
    _p(b, {"action": "load_clashes", "clashes": [
        {"id": "c1", "state": "verified_conditional", "unprovable_checks": ["boundary.ports", "integrity.access"]},
    ]})
    r = _p(b, {"action": "approve", "acknowledge_unprovable": ["boundary.ports"]})
    assert r["status"] == "refused"
    assert r["detail"]["unacknowledged"] == ["integrity.access"]
    # a blanket approval is exactly the rubber stamp this refuses
    r2 = _p(b, {"action": "approve", "acknowledge_unprovable": []})
    assert r2["status"] == "refused"


def test_approve_with_full_acknowledgement_merges():
    b = MepReviewLedgerBlock()
    _p(b, {"action": "load_clashes", "clashes": [
        {"id": "c1", "state": "verified_conditional", "unprovable_checks": ["boundary.ports"]},
        {"id": "c2", "state": "verified"},
        {"id": "c3", "state": "proposed"},
    ]})
    r = _p(b, {"action": "approve", "acknowledge_unprovable": ["boundary.ports"]})
    assert r["status"] == "ok"
    assert r["result"]["review"]["clashes_merged"] == 2
    assert r["result"]["review"]["approved_fully"] == 1
    assert r["result"]["review"]["approved_conditionally"] == 1
    # proposed (unverified) clashes are never approved
    reviews = _p(b, {"action": "list_reviews"})
    assert reviews["result"]["count"] == 1


def test_reject_reopens_eligible_clashes_only():
    b = MepReviewLedgerBlock()
    _p(b, {"action": "load_clashes", "clashes": [
        {"id": "c1", "state": "verified"},
        {"id": "c2", "state": "proposed"},
        {"id": "c3", "state": "merged"},
    ]})
    r = _p(b, {"action": "reject", "notes": "redo"})
    assert r["status"] == "ok"
    assert r["result"]["review"]["clashes_reopened"] == 2
    assert r["result"]["review"]["notes"] == "redo"


def test_edit_requires_at_least_one_edit():
    b = MepReviewLedgerBlock()
    assert _p(b, {"action": "edit", "edits": []})["status"] == "refused"


def test_edit_maps_monitor_verdicts_like_the_donor():
    b = MepReviewLedgerBlock()
    r = _p(b, {"action": "edit", "edits": [
        {"clash_id": "c1", "verdict": "pass", "unprovable_checks": [], "objections": []},
        {"clash_id": "c2", "verdict": "fail", "unprovable_checks": [], "objections": ["geometry: pushes duct"]},
        {"clash_id": "c3", "verdict": "conditional", "unprovable_checks": ["boundary.ports"], "objections": []},
    ]})
    assert r["status"] == "ok"
    edits = {e["clash_id"]: e for e in r["result"]["edits"]}
    assert edits["c1"]["passed"] is True
    assert edits["c2"]["objections"] == ["geometry: pushes duct"]
    assert edits["c3"]["unprovable_checks"] == ["boundary.ports"]


# -- deliverable enrichment (review_package.py) ---------------------------------

def test_enrich_change_set_carries_the_verification_distinction():
    b = MepReviewLedgerBlock()
    change_set = {"entries": [
        {"clash_id": "c1", "move": [1, 0, 0]},
        {"clash_id": "c2", "move": [0, 2, 0]},
    ]}
    r = _p(b, {"action": "enrich_change_set", "change_set": change_set, "by_clash": {
        "c1": {"verification": "conditional", "unprovable_checks": ["boundary.ports"]},
    }})
    assert r["status"] == "ok"
    out = r["result"]["change_set"]
    entries = {e["clash_id"]: e for e in out["entries"]}
    assert entries["c1"]["verification"] == "conditional"
    assert entries["c1"]["unprovable_checks"] == ["boundary.ports"]
    assert "accepting" in entries["c1"]["verification_note"].lower()
    assert entries["c2"]["verification"] == "full"
    assert out["verification_summary"]["fully_verified"] == 1
    assert out["verification_summary"]["conditionally_verified"] == 1


def test_annotate_bcf_adds_verification_comments(tmp_path: Path):
    b = MepReviewLedgerBlock()
    bcf = tmp_path / "out.bcfzip"
    topic_id = "topic-1"
    with zipfile.ZipFile(bcf, "w") as zf:
        zf.writestr(
            "topic-1/markup.bcf",
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Markup><Topic><Title>g1 vs g2</Title></Topic>"
            "<Comment><Comment>no comment</Comment></Comment></Markup>",
        )
    r = _p(b, {"action": "annotate_bcf", "path": str(bcf), "by_pair": [
        {"gids": ["g1", "g2"], "verification": "conditional", "unprovable_checks": ["boundary.ports"]},
    ]})
    assert r["status"] == "ok"
    with zipfile.ZipFile(str(bcf)) as zf:
        body = zf.read("topic-1/markup.bcf").decode("utf-8")
    assert "conditional" in body
    assert "boundary.ports" in body


def test_annotate_bcf_missing_path_is_error():
    b = MepReviewLedgerBlock()
    assert _p(b, {"action": "annotate_bcf", "path": "C:/no/such.bcfzip"})["status"] == "error"


def test_verification_of_maps_verdicts():
    b = MepReviewLedgerBlock()
    assert _p(b, {"action": "verification_of", "verdict": "verified_conditional"})["result"]["verification"] == "conditional"
    assert _p(b, {"action": "verification_of", "verdict": "verified"})["result"]["verification"] == "full"


def test_bad_inputs_are_errors():
    b = MepReviewLedgerBlock()
    assert _p(b, {"action": "aggregate", "results": "nope"})["status"] == "error"
    assert _p(b, {"action": "enrich_change_set"})["status"] == "error"
    assert _p(b, {"action": "nope"})["status"] == "error"
