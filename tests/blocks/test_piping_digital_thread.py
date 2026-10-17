"""Piping digital thread — ported <private-repo> src/<private-repo> package.

Tests ported from the donor's tests/test_clash.py and tests/test_tables.py
(clash geometry, engineering tables, A* routing, cascade, maturity, PCF),
plus the block facade's refusal paths.
"""
from __future__ import annotations

import asyncio

import pytest

from app.blocks.piping_digital_thread import PipingDigitalThreadBlock, build_graph
from app.blocks.piping_digital_thread.clash import (
    capsule_aabb,
    capsule_capsule,
    capsule_cylinder,
    segment_distance,
)
from app.blocks.piping_digital_thread.models import DesignVolume, Equipment, Nozzle, Pipeline
from app.blocks.piping_digital_thread.tables import (
    flange_bolts,
    hydrotest_pressure_barg,
    mass_per_m,
    od_mm,
    support_span_m,
    wall_thickness_mm,
)


def _run(coro):
    return asyncio.run(coro)


def _p(b, payload):
    return _run(b.process(payload))


def _graph_spec():
    return {
        "volumes": [{"id": "V", "name": "V", "xmin": -5, "ymin": -5, "zmin": 0, "xmax": 20, "ymax": 20, "zmax": 15}],
        "equipment": [
            {"id": "E1", "tag": "E1", "nozzles": ["E1-N1"], "volume_id": "V"},
            {"id": "E2", "tag": "E2", "nozzles": ["E2-N1"], "volume_id": "V"},
            {"id": "E3", "tag": "E3", "nozzles": ["E3-N1"], "volume_id": "V"},
            {"id": "E4", "tag": "E4", "nozzles": ["E4-N1"], "volume_id": "V"},
        ],
        "nozzles": [
            {"id": "E1-N1", "tag": "N1", "equipment_id": "E1", "x": 0, "y": 5, "z": 5},
            {"id": "E2-N1", "tag": "N1", "equipment_id": "E2", "x": 10, "y": 5, "z": 5},
            {"id": "E3-N1", "tag": "N1", "equipment_id": "E3", "x": 5, "y": 0, "z": 5},
            {"id": "E4-N1", "tag": "N1", "equipment_id": "E4", "x": 5, "y": 10, "z": 5},
        ],
        "pipelines": [
            {"id": "L1", "line_number": "L1", "from_tag": "E1-N1", "to_tag": "E2-N1", "nominal_bore": '6"', "service": "PROCESS"},
            {"id": "L2", "line_number": "L2", "from_tag": "E3-N1", "to_tag": "E4-N1", "nominal_bore": '6"', "service": "PROCESS"},
        ],
    }


# -- clash geometry (donor tests/test_clash.py) -------------------------------

def test_segment_distance_parallel():
    d, _, _ = segment_distance((0, 0, 0), (10, 0, 0), (0, 1, 0), (10, 1, 0))
    assert abs(d - 1.0) < 1e-9


def test_segment_distance_skew():
    d, _, _ = segment_distance((0, 0, 0), (10, 0, 0), (1, -5, 2), (1, 5, 2))
    assert abs(d - 2.0) < 1e-9


def test_segment_distance_touching():
    d, _, _ = segment_distance((0, 0, 0), (1, 0, 0), (1, 0, 0), (2, 0, 0))
    assert abs(d) < 1e-9


def test_capsule_capsule_hard():
    r = capsule_capsule((0, 0, 0), (10, 0, 0), 0.3, (0, 0.5, 0), (10, 0.5, 0), 0.3)
    assert r["hard"] is True
    assert abs(r["penetration"] - 0.1) < 1e-9


def test_capsule_aabb_and_cylinder():
    box = (4.0, -1.0, -1.0, 6.0, 1.0, 1.0)
    hit = capsule_aabb((0, 0, 0), (10, 0, 0), 0.1, box)
    assert hit["hard"] is True
    cyl = capsule_cylinder((0, 0, 0), (10, 0, 0), 0.2, (5, 0.3, 0), (5, 0.3, 5), 0.2)
    assert cyl["distance"] < 0.35


def test_clash_check_crossing_routes_via_block():
    b = PipingDigitalThreadBlock()
    routes = [
        {"line_id": "L1", "line_number": "L1", "nominal_bore": '6"',
         "points": [{"x": 0, "y": 5, "z": 5}, {"x": 10, "y": 5, "z": 5}]},
        {"line_id": "L2", "line_number": "L2", "nominal_bore": '6"',
         "points": [{"x": 5, "y": 0, "z": 5}, {"x": 5, "y": 10, "z": 5}]},
    ]
    r = _p(b, {"action": "clash_check", "graph": _graph_spec(), "routes": routes, "clearance": 0.05})
    assert r["status"] == "ok"
    assert r["result"]["report"]["hard_count"] >= 1
    tags = {tuple(c["tags"]) for c in r["result"]["report"]["clashes"]}
    assert ("L1", "L2") in tags or ("L2", "L1") in tags


# -- engineering tables (donor tests/test_tables.py) --------------------------

def test_six_inch_sch40_weight_within_1pct():
    kg = mass_per_m('6"', "40")
    assert abs(kg - 28.26) / 28.26 <= 0.01


def test_od_and_wall_b36():
    assert abs(od_mm('6"') - 168.3) < 0.05
    assert abs(wall_thickness_mm('6"', "40") - 7.11) < 0.05


def test_support_span_mss():
    assert support_span_m('6"') == 5.2
    assert support_span_m('2"') == 3.4


def test_flange_bolts_b16_5():
    assert flange_bolts('6"', 150) == (8, 0.75)


def test_test_pressure_b31_3():
    assert hydrotest_pressure_barg(10.0) == 15.0
    assert hydrotest_pressure_barg(None) is None


# -- routing / graph -----------------------------------------------------------

def test_build_graph_and_summary():
    graph = build_graph(_graph_spec())
    s = graph.connectivity_summary()
    assert s["pipeline_count"] == 2
    assert s["equipment_count"] == 4
    assert s["volume_count"] == 1


def test_route_astar_populates_routes_and_keeps_hard_clashes_zero():
    b = PipingDigitalThreadBlock()
    r = _p(b, {"action": "route_astar", "graph": _graph_spec()})
    assert r["status"] == "ok"
    assert r["result"]["route_count"] == 2
    report = _p(b, {"action": "clash_check", "graph": _graph_spec()})
    # A* routes avoid the crossing; hard clashes stay at zero for this spec
    assert report["result"]["report"]["hard_count"] == 0


# -- maturity / cascade --------------------------------------------------------

def test_maturity_levels_from_graph_completeness():
    b = PipingDigitalThreadBlock()
    r = _p(b, {"action": "maturity", "graph": _graph_spec()})
    assert r["status"] == "ok"
    assert "level" in r["result"]["maturity"]


def test_cascade_marks_downstream_artefacts_dirty():
    b = PipingDigitalThreadBlock()
    r = _p(b, {"action": "cascade", "graph": _graph_spec(),
               "change": {"entity_type": "tag", "entity_id": "E1"}})
    assert r["status"] == "ok"
    assert r["result"]["dirty"]["dirty"] is True
    assert "routes" in r["result"]["dirty"]["artefact_kinds"]


# -- PCF -----------------------------------------------------------------------

def test_pcf_text_contains_iso_header():
    b = PipingDigitalThreadBlock()
    r = _p(b, {"action": "pcf_text", "graph": _graph_spec(), "line_id": "L1"})
    assert r["status"] == "ok"
    assert "<private-repo> PCF" in r["result"]["pcf"]
    assert "UNITS-BORE" in r["result"]["pcf"]
    assert "L1" in r["result"]["pcf"]


def test_pcf_text_unknown_line_is_error():
    b = PipingDigitalThreadBlock()
    r = _p(b, {"action": "pcf_text", "graph": _graph_spec(), "line_id": "NOPE"})
    assert r["status"] == "error"


# -- 4D schedule ---------------------------------------------------------------

def test_schedule4d_co_activity_and_look_ahead():
    b = PipingDigitalThreadBlock()
    activities = [{"id": "a1", "discipline": "PIP", "start": "2026-07-01", "finish": "2026-07-10"}]
    r = _p(b, {"action": "schedule4d", "graph": {"volumes": []}, "activities": activities, "mode": "co_activity"})
    assert r["status"] == "ok"
    assert r["result"]["activities_loaded"] == 1
    la = _p(b, {"action": "schedule4d", "graph": {"volumes": []}, "activities": activities,
                "mode": "look_ahead", "weeks": 2, "from_date": "2026-07-05"})
    assert la["result"]["look_ahead"]["activity_count"] == 1
    assert la["result"]["look_ahead"]["by_discipline"] == {"PIP": 1}


def test_schedule4d_requires_activities():
    b = PipingDigitalThreadBlock()
    assert _p(b, {"action": "schedule4d", "graph": {"volumes": []}, "activities": []})["status"] == "error"


# -- facade refusals -----------------------------------------------------------

def test_unknown_actions_and_missing_graphs():
    b = PipingDigitalThreadBlock()
    assert _p(b, {"action": "bogus"})["status"] == "error"
    assert _p(b, {"action": "summary", "graph": "nope"})["status"] == "error"
    assert _p(b, {"action": "tables", "fn": "bogus"})["status"] == "error"
