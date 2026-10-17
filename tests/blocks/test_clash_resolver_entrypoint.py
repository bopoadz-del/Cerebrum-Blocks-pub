"""clash_resolver: the ADVERTISED entry point, and it runs everywhere.

tests/blocks/test_clash_resolver.py is 374 lines of good tests behind a
module-level ``pytest.importorskip("trimesh")``. trimesh is a genuine
requirement of app/blocks/clash_resolver.py's neighbourhood re-check, but it
was in no requirements file, so that entire suite skipped by default -- and
none of it constructed ``ClashResolverBlock`` anyway.

This file covers the dispatcher the registry advertises and does it without a
geometry backend, deliberately: every element here carries ``mesh=None``, so
``_would_create_new_clash`` returns before it imports geometry_engine. What is
under test is the part of the block that is pure decision -- which axes a
gravity run may move along, how far, and whether an unsourced number is
allowed to be called a proposal -- plus the two refusals
``block_registry/clash_resolver/block.json`` lists as acceptance criteria.

The mesh-backed neighbourhood and batch-rollback behaviour stays where it is,
in the trimesh-gated file; this file does not duplicate or weaken it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

from app.blocks.clash_resolver import (
    DEFAULT_MARGIN_MM,
    MOVE_ELEVATION,
    MOVE_OFFSET,
    MOVE_SLEEVE,
    STATUS_FLAGGED,
    STATUS_PROPOSED,
    ClashResolverBlock,
)


@dataclass
class El:
    global_id: str
    discipline: str = "mep"
    is_gravity: bool = False
    mesh: object = None


@dataclass
class Item:
    clash_id: str = "CL-001"


def _magnitude(v):
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


async def test_process_resolve_proposes_a_sourced_move_of_the_distance_the_rule_requires():
    """The proposal carries a vector whose length is the required gap plus
    the installation margin -- a number the block computed -- and the clause
    that authorises it."""
    env = await ClashResolverBlock().process({
        "action": "resolve",
        "item": Item(),
        "element": El("DRAIN-9"),
        "neighbours": [],
        "required_gap_mm": 100.0,
        "rule_ids": ["SBC-501-X"],
        "clause_text": "Minimum 100 mm clear between services.",
    })

    assert env["status"] == "ok"
    assert env["error"] is None
    proposal = env["result"]

    assert proposal.status == STATUS_PROPOSED
    assert proposal.clash_id == "CL-001"
    assert proposal.element == "DRAIN-9"
    assert proposal.rule_ids == ["SBC-501-X"]
    assert proposal.clause_text == "Minimum 100 mm clear between services."
    # Smallest-displacement-first: the very first candidate survives, so the
    # move is exactly gap + margin, never a bigger one picked at random.
    assert _magnitude(proposal.move_vector_mm) == pytest.approx(
        100.0 + DEFAULT_MARGIN_MM, abs=0.01
    )
    assert proposal.attempts == 1
    assert proposal.rejected == []
    assert proposal.note is None


async def test_process_resolve_never_takes_a_gravity_run_vertical():
    """The one failure this block must never allow: lifting a drain to clear
    a duct. The proposed vector has no Z component at all."""
    env = await ClashResolverBlock().process({
        "action": "resolve",
        "item": Item("CL-GRAV"),
        "element": El("SOIL-STACK-2", is_gravity=True),
        "neighbours": [],
        "required_gap_mm": 100.0,
        "rule_ids": ["SBC-501-X"],
        "clause_text": "Minimum 100 mm clear between services.",
    })

    proposal = env["result"]
    assert proposal.status == STATUS_PROPOSED
    assert proposal.move_vector_mm[2] == 0.0
    assert proposal.move_type == MOVE_OFFSET
    # Still a full-size move -- laterally.
    assert math.hypot(*proposal.move_vector_mm[:2]) == pytest.approx(
        100.0 + DEFAULT_MARGIN_MM, abs=0.01
    )


async def test_process_resolve_flags_an_unsourced_move_instead_of_proposing_it():
    """A geometrically valid move with no clause behind it is FLAGGED. The
    distinction is the block's whole claim to being trustworthy: a proposal
    invites an engineer to accept it."""
    env = await ClashResolverBlock().process({
        "action": "resolve",
        "item": Item("CL-002"),
        "element": El("VAV-4"),
        "neighbours": [],
        "required_gap_mm": 75.0,
    })

    proposal = env["result"]
    assert proposal.status == STATUS_FLAGGED
    assert proposal.rule_ids == []
    assert proposal.clause_text is None
    assert "no clause authorises the clearance" in proposal.note
    assert "requires an engineer's decision" in proposal.note
    # It is still a real move, sized by the gap it was given.
    assert _magnitude(proposal.move_vector_mm) == pytest.approx(
        75.0 + DEFAULT_MARGIN_MM, abs=0.01
    )


async def test_process_candidates_withholds_the_z_axis_from_a_gravity_run():
    """The candidate set itself, not just the chosen move: a gravity element
    is offered lateral and diagonal moves only, an ordinary one is offered
    elevation changes too."""
    block = ClashResolverBlock()

    gravity = await block.process({
        "action": "candidates",
        "item": Item(),
        "element": El("SOIL-STACK-2", is_gravity=True),
        "required_gap_mm": 100.0,
    })
    ordinary = await block.process({
        "action": "candidates",
        "item": Item(),
        "element": El("DUCT-7"),
        "required_gap_mm": 100.0,
    })

    assert gravity["status"] == "ok" and ordinary["status"] == "ok"
    gravity_moves = gravity["result"]
    ordinary_moves = ordinary["result"]

    # 2 free axes: 4 axis directions + 4 diagonals, over 4 distance steps.
    assert len(gravity_moves) == 32
    assert all(vector[2] == 0.0 for _, vector in gravity_moves)
    assert not any(move == MOVE_ELEVATION for move, _ in gravity_moves)

    # 3 free axes: 6 axis directions + 12 diagonals, over 4 distance steps.
    assert len(ordinary_moves) == 72
    assert any(vector[2] != 0.0 for _, vector in ordinary_moves)
    assert any(move == MOVE_ELEVATION for move, _ in ordinary_moves)


async def test_process_candidates_are_ordered_least_invasive_first():
    """Ordering is a safety property: the caller takes the first candidate
    that passes, so a bigger move can only ever be chosen because the
    smaller ones were rejected."""
    env = await ClashResolverBlock().process({
        "action": "candidates",
        "item": Item(),
        "element": El("DUCT-7"),
        "required_gap_mm": 100.0,
        "margin_mm": 25.0,
    })

    magnitudes = [_magnitude(v) for _, v in env["result"]]
    assert magnitudes == sorted(magnitudes)
    # First candidate is need = gap + margin; last is 3 x need.
    assert magnitudes[0] == pytest.approx(125.0, abs=0.01)
    assert magnitudes[-1] == pytest.approx(375.0, abs=0.03)


async def test_process_candidates_sleeves_through_structure_rather_than_moving_it():
    env = await ClashResolverBlock().process({
        "action": "candidates",
        "item": Item(),
        "element": El("BEAM-11", discipline="structural"),
        "required_gap_mm": 100.0,
    })

    assert env["result"] == [(MOVE_SLEEVE, (0.0, 0.0, 0.0))]


async def test_process_refuses_an_unknown_action():
    """block.json acceptance criterion 'unknown_action'."""
    env = await ClashResolverBlock().process({"action": "apply"})

    assert env["status"] == "error"
    assert env["error"] == "unknown action: apply"
    assert env["detail"] == {"known": ["candidates", "resolve", "verify"]}
    assert env["result"] is None


async def test_process_refuses_candidates_with_no_element_or_gap():
    """block.json acceptance criterion 'missing_arguments': an empty payload
    is refused, not answered with an empty candidate list."""
    env = await ClashResolverBlock().process({"action": "candidates"})

    assert env["status"] == "error"
    assert env["error"].startswith("missing or invalid arguments:")
    assert "required_gap_mm" in env["error"]
    assert env["detail"]["required"] == [
        "item", "element", "required_gap_mm", "margin_mm", "steps",
    ]


async def test_process_refuses_an_empty_payload_instead_of_resolving_nothing():
    """The default action is 'resolve'; an empty dict must not come back as a
    resolved clash."""
    env = await ClashResolverBlock().process({})

    assert env["status"] == "error"
    assert env["error"].startswith("missing or invalid arguments:")
    assert env["detail"]["required"][0] == "item"


async def test_execute_returns_the_process_envelope_unchanged():
    env = await ClashResolverBlock().execute({
        "action": "resolve",
        "item": Item("CL-777"),
        "element": El("PIPE-3"),
        "neighbours": [],
        "required_gap_mm": 50.0,
        "rule_ids": ["R-1"],
        "clause_text": "50 mm.",
    })

    assert env["block_id"] == "clash_resolver"
    assert env["status"] == "ok"
    assert env["result"].clash_id == "CL-777"
    assert env["result"].status == STATUS_PROPOSED
    assert _magnitude(env["result"].move_vector_mm) == pytest.approx(
        50.0 + DEFAULT_MARGIN_MM, abs=0.01
    )
