"""MEP zoning â€” ported <private-repo> app/agents/zoning.py.

Deterministic cell merging, riser/corridor dedicated zones, bbox buffers
and buffer-owner neighbour maps.
"""
from __future__ import annotations

import asyncio

from app.blocks.mep_zoning import MepZoningBlock


def _run(coro):
    return asyncio.run(coro)


def _p(b, payload):
    return _run(b.process(payload))


def _elements():
    return [
        {"global_id": "g1", "name": "duct run", "level": "L1", "system": "vent", "bbox": [0, 0, 0, 1, 1, 1]},
        {"global_id": "g2", "name": "riser stack A", "level": "L1", "system": "vent", "bbox": [10, 10, 0, 11, 11, 9]},
        {"global_id": "g3", "name": "cable corridor", "level": "L1", "system": "elec", "bbox": [20, 0, 0, 30, 1, 1]},
        {"global_id": "g4", "name": "duct", "level": "L2", "system": "vent", "bbox": [0, 0, 4, 1, 1, 5]},
        {"global_id": "g5", "name": "pipe", "level": "L1", "system": "water", "bbox": [0.5, 0.5, 0, 2, 2, 2]},
    ]


def test_plan_zones_is_deterministic_and_merges_cells():
    b = MepZoningBlock()
    r1 = _p(b, {"action": "plan_zones", "elements": _elements(), "max_elements": 2, "cell_m": 6.0})
    r2 = _p(b, {"action": "plan_zones", "elements": _elements(), "max_elements": 2, "cell_m": 6.0})
    assert r1["status"] == "ok"
    assert r1["result"]["zones"] == r2["result"]["zones"]  # same model -> same zones
    zones = {z["zone_key"]: z for z in r1["result"]["zones"]}
    # g1+g5 share L1|0_0 and merge under the ceiling
    assert sorted(zones["L1|0_0"]["element_gids"]) == ["g1", "g5"]
    assert zones["L1|0_0"]["element_count"] == 2


def test_riser_and_corridor_get_dedicated_zones():
    b = MepZoningBlock()
    r = _p(b, {"action": "plan_zones", "elements": _elements(), "max_elements": 2})
    zones = {z["zone_key"]: z for z in r["result"]["zones"]}
    assert "riser_or_shaft|vent" in zones
    assert zones["riser_or_shaft|vent"]["element_gids"] == ["g2"]
    assert zones["riser_or_shaft|vent"]["dedicated_reason"] == "riser_or_shaft"
    assert "main_corridor|elec" in zones
    assert zones["main_corridor|elec"]["element_gids"] == ["g3"]


def test_levels_are_split_into_separate_zones():
    b = MepZoningBlock()
    r = _p(b, {"action": "plan_zones", "elements": _elements(), "max_elements": 2})
    keys = [z["zone_key"] for z in r["result"]["zones"]]
    assert "L1|0_0" in keys and "L2|0_0" in keys


def test_zone_key_grid_math():
    b = MepZoningBlock()
    # bbox centre (0.5, 0.5) -> cell 0_0
    assert _p(b, {"action": "zone_key", "element": _elements()[0]})["result"]["zone_key"] == "L1|0_0"
    # centre (10.5, 10.5) -> cell 1_1 at 6 m
    assert _p(b, {"action": "zone_key", "element": _elements()[1]})["result"]["zone_key"] == "L1|1_1"
    # no bbox -> nocell
    r = _p(b, {"action": "zone_key", "element": {"global_id": "g9", "level": "L1"}})
    assert r["result"]["zone_key"] == "L1|nocell"


def test_buffer_gids_includes_nearby_out_of_zone_elements():
    b = MepZoningBlock()
    plan = {"zone_key": "z1", "level": "L1", "grid_cell": "0_0",
            "element_gids": ["a1", "a2"], "member_cells": []}
    elements = {
        "a1": {"global_id": "a1", "name": "duct", "level": "L1", "system": "vent", "bbox": [0, 0, 0, 1, 1, 1]},
        "a2": {"global_id": "a2", "name": "pipe", "level": "L1", "system": "water", "bbox": [0.5, 0.5, 0, 2, 2, 2]},
        # just outside the zone but within the buffer
        "near": {"global_id": "near", "name": "cable", "level": "L1", "system": "elec", "bbox": [1.2, 0, 0, 2.0, 1, 1]},
        # far away
        "far": {"global_id": "far", "name": "cable", "level": "L1", "system": "elec", "bbox": [50, 50, 0, 51, 51, 1]},
    }
    rb = _p(b, {"action": "buffer_gids", "plan": plan, "elements_by_id": elements, "buffer_m": 0.5})
    assert rb["status"] == "ok"
    assert "near" in rb["result"]["buffer_gids"]
    assert "far" not in rb["result"]["buffer_gids"]
    assert "a1" not in rb["result"]["buffer_gids"]  # own zone excluded


def test_neighbours_of_maps_buffer_elements_to_owning_zones():
    b = MepZoningBlock()
    plan = {"zone_key": "z1", "level": "L1", "grid_cell": "0_0", "element_gids": ["a1"], "member_cells": []}
    other = {"zone_key": "z2", "level": "L1", "grid_cell": "1_0", "element_gids": ["near"], "member_cells": []}
    rn = _p(b, {"action": "neighbours_of", "plan": plan, "plans": [plan, other], "buffer_ids": ["near", "orphan"]})
    assert rn["status"] == "ok"
    neighbours = rn["result"]["neighbours"]
    assert neighbours == {"z2": ["near"]}
    # an element nobody owns is not attributed to any zone
    assert "orphan" not in [g for gids in neighbours.values() for g in gids]


def test_bad_inputs_are_errors():
    b = MepZoningBlock()
    assert _p(b, {"action": "plan_zones", "elements": "nope"})["status"] == "error"
    assert _p(b, {"action": "buffer_gids"})["status"] == "error"
    assert _p(b, {"action": "neighbours_of"})["status"] == "error"
    assert _p(b, {"action": "zone_key"})["status"] == "error"
    assert _p(b, {"action": "bogus"})["status"] == "error"
