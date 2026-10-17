"""CPM engine tests - ported behavior from The_Fork pm_computations + cpm_engine."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.cpm_engine import CpmEngineBlock
from app.lib.pm_computations import CircularDependencyError, compute_cpm, topological_order
from app.schemas.cpm import Activity, CPMInput


def _run(coro):
    return asyncio.run(coro)


def _linear():
    return [
        {"id": "A", "name": "Excavate", "duration": 5, "predecessors": []},
        {"id": "B", "name": "Foundations", "duration": 10, "predecessors": [{"predecessor_id": "A", "type": "FS", "lag": 0}]},
        {"id": "C", "name": "Frame", "duration": 15, "predecessors": [{"predecessor_id": "B", "type": "FS", "lag": 0}]},
    ]


def test_forward_backward_float_and_critical_path():
    b = CpmEngineBlock()
    r = _run(b.process({"action": "compute", "activities": _linear()}))
    assert r["status"] == "ok"
    res = {x["id"]: x for x in r["result"]["results"]}
    assert res["A"]["early_start_day"] == 0 and res["A"]["early_finish_day"] == 5
    assert res["B"]["early_start_day"] == 5 and res["B"]["early_finish_day"] == 15
    assert res["C"]["early_start_day"] == 15 and res["C"]["early_finish_day"] == 30
    assert r["result"]["project_duration"] == 30
    assert r["result"]["critical_path"] == ["A", "B", "C"]
    assert all(res[i]["total_float"] == 0 for i in "ABC")


def test_circular_dependency_fails_loud():
    b = CpmEngineBlock()
    acts = [
        {"id": "A", "duration": 2, "predecessors": [{"predecessor_id": "B", "type": "FS"}]},
        {"id": "B", "duration": 2, "predecessors": [{"predecessor_id": "A", "type": "FS"}]},
    ]
    r = _run(b.process({"action": "compute", "activities": acts}))
    assert r["status"] == "failed"
    assert "Circular" in r["error"]
    # The library itself raises the typed error.
    try:
        topological_order([Activity(**a) for a in acts])
        assert False, "cycle must raise"
    except CircularDependencyError:
        pass


def test_unknown_predecessor_fails_loud():
    b = CpmEngineBlock()
    r = _run(b.process({"action": "compute", "activities": [
        {"id": "A", "duration": 2, "predecessors": [{"predecessor_id": "GHOST", "type": "FS"}]},
    ]}))
    assert r["status"] == "failed"
    assert "GHOST" in r["error"]


def test_no_activities_is_refused():
    b = CpmEngineBlock()
    assert _run(b.process({"action": "compute"}))["status"] == "refused"
    assert _run(b.process({"action": "histogram"}))["status"] == "refused"
    assert _run(b.process({"action": "gantt"}))["status"] == "refused"
    assert _run(b.process({"action": "compress"}))["status"] == "refused"


def test_resource_histogram_periods():
    b = CpmEngineBlock()
    r = _run(b.process({
        "action": "histogram", "activities": _linear(), "period_unit": "week",
    }))
    assert r["status"] == "ok"
    assert r["result"]["period_unit"] == "week"
    assert len(r["result"]["periods"]) >= 1
    assert r["result"]["peak_total"] >= 0


def test_gantt_bars_cover_every_activity():
    b = CpmEngineBlock()
    r = _run(b.process({"action": "gantt", "activities": _linear()}))
    assert {x["id"] for x in r["result"]["bars"]} == {"A", "B", "C"}


def test_compress_reports_days_saved():
    b = CpmEngineBlock()
    r = _run(b.process({
        "action": "compress", "activities": _linear(),
        "reductions": {"C": 10},
    }))
    assert r["status"] == "ok"
    assert r["result"]["days_saved"] == 10
    assert r["result"]["project_duration"] == 20


def test_compress_unknown_id_fails_loud():
    b = CpmEngineBlock()
    r = _run(b.process({
        "action": "compress", "activities": _linear(), "reductions": {"NOPE": 1},
    }))
    assert r["status"] == "failed"
    assert "NOPE" in r["error"]


def test_parse_xer_tokenizes_tables():
    b = CpmEngineBlock()
    xer = (
        "%T\tTASK\n"
        "%F\ttask_id\ttask_name\ttarget_drtn_hr_cnt\n"
        "%R\tA1000\tExcavate\t40\n"
        "%R\tA1010\tFoundations\t80\n"
        "%T\tTASKPRED\n"
        "%F\ttask_id\tpred_task_id\tpred_type\tlag_hr_cnt\n"
        "%R\tA1010\tA1000\tPR_FS\t0\n"
        "%E\n"
    )
    r = _run(b.process({"action": "parse_xer", "text": xer}))
    assert r["status"] == "ok"
    assert {a["id"] for a in r["result"]["activities"]} == {"A1000", "A1010"}
    full = _run(b.process({"action": "parse_xer_full", "text": xer}))
    assert full["result"]["activities"][0]["id"] == "A1000"


def test_parse_xer_empty_text_is_refused():
    b = CpmEngineBlock()
    assert _run(b.process({"action": "parse_xer"}))["status"] == "refused"
    assert _run(b.process({"action": "parse_xer", "text": "   "}))["status"] == "refused"


def test_lookahead_filters_by_window():
    b = CpmEngineBlock()
    acts = [
        {"id": "1", "start": "2026-09-01", "finish": "2026-09-05"},
        {"id": "2", "start": "2027-01-01", "finish": "2027-01-05"},
        {"id": "3", "name": "no dates"},
    ]
    r = _run(b.process({"action": "lookahead", "activities": acts,
                        "as_of": "2026-09-01", "window_days": 21}))
    assert r["status"] == "ok"
    assert [a["id"] for a in r["result"]["activities"]] == ["1"]


def test_lookahead_bad_window_is_refused():
    b = CpmEngineBlock()
    r = _run(b.process({"action": "lookahead", "activities": [], "window_days": 0}))
    assert r["status"] == "refused"


def test_write_excel_round_trips(tmp_path):
    b = CpmEngineBlock()
    out = tmp_path / "schedule.xlsx"
    r = _run(b.process({"action": "write_excel", "activities": _linear(), "path": str(out)}))
    assert r["status"] == "ok"
    assert out.exists() and out.stat().st_size > 0


def test_write_excel_without_path_is_refused():
    b = CpmEngineBlock()
    r = _run(b.process({"action": "write_excel", "activities": _linear()}))
    assert r["status"] == "refused"


def test_cpm_library_is_the_donor_engine():
    # The wholesale library port itself: forward pass over the donor schema.
    acts = [Activity(id="A", duration=5), Activity(id="B", duration=10,
            predecessors=[{"predecessor_id": "A", "type": "FS"}])]
    out = compute_cpm(CPMInput(activities=acts))
    assert out.project_duration == 15
    assert [r.id for r in out.results if r.is_critical] == ["A", "B"]


def test_unknown_action_is_error():
    b = CpmEngineBlock()
    r = _run(b.process({"action": "nonsense"}))
    assert r["status"] == "error"
    assert r["block_id"] == "cpm_engine"
