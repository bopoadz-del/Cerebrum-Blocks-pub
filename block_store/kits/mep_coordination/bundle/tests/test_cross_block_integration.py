"""Cross-block integration: the real B1 -> B3 -> B4 -> B7 pipeline, run end
to end on constructed geometry.

WHY THIS TEST EXISTS
This kit shipped a real production bug: clash_triage derived a clash id as
"A__B" while version_diff derived "A::B" for the identical pair of elements.
Every unit test in both modules passed -- each suite checked its module's
output only against itself. The mismatch surfaced three blocks downstream,
in score_proposals, as a permanent, silent 0.0: no proposal's clash_id could
ever match an entry in diff_versions' "resolved" bucket, and 0.0 is exactly
the number you would expect from "nothing has been fixed yet", so nobody
noticed. Green units, silent zero.

No per-module unit test would have caught it, by construction -- catching it
needs the actual output of one block fed into the next, using the real
public entry points (not fakes standing in for them). That is what this file
does: geometry_engine.judge_pair -> clash_triage.triage ->
clash_resolver.resolve -> version_diff.diff_versions -> score_proposals, on
six constructed elements, with a real overlap and a real clearance shortfall
planted on purpose.

No IFC file is used or needed. The 47 MB acceptance fixture is gitignored
(see fixtures/FIXTURES.md) and CI will not have it; every block under test
only ever looks at `.mesh`, `.global_id`, `.system`, and a handful of other
plain attributes, so a trimesh box is exactly as valid an input as a
meshed IFC product.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any

import pytest

trimesh = pytest.importorskip("trimesh", reason="geometry backend not installed")

from app.blocks import clash_resolver, clash_triage, version_diff
from app.blocks.geometry_engine import judge_pair


@dataclass
class Element:
    """Everything B1/B3/B4/B7 read off an element, and nothing more.

    Deliberately NOT ``ifc_loader.Element`` -- that dataclass is only ever
    populated by parsing an actual IFC file, which is precisely the
    dependency this test exists to avoid. Every field here is exactly what
    the order specifies: global_id, system, discipline, name, level,
    zone_key, bbox, mesh, is_gravity.
    """

    global_id: str
    system: str
    discipline: str
    name: str
    level: str
    zone_key: str
    mesh: Any
    is_gravity: bool = False
    bbox: tuple = ()

    def __post_init__(self) -> None:
        if not self.bbox:
            self.bbox = tuple(float(v) for v in self.mesh.bounds.flatten())


def _box(size, at):
    m = trimesh.creation.box(extents=size)
    m.apply_translation(at)
    return m


def _build_elements() -> list[Element]:
    """Six elements, two planted findings, on real (if simple) geometry.

    * D1 (ventilation duct) and E1 (electrical tray) physically overlap --
      a real hard clash: their boxes interpenetrate, no rule needed to see
      it, exactly like an AABB-vs-mesh disagreement geometry_engine exists
      to resolve correctly.
    * F1 and F2 (a fire main and a chilled-water pipe) sit exactly 200mm
      apart. A 300mm minimum-gap rule is applied to that pair in
      ``_judge_all_pairs`` below -- a real clearance violation, not a hard
      clash.
    * G1 (a gravity drain) and W1 (a structural wall) sit far from
      everything else and from each other. They exist so the pipeline is
      exercised on elements that are clean in both versions, the same way
      a real model has far more clean pairs than conflicted ones.
    """
    d1 = Element(
        "D1", "ventilation", "mep", "supply air duct", "L1", "L1|0_0",
        _box((0.3, 0.3, 0.3), (0.0, 0.0, 0.0)),
    )
    e1 = Element(
        "E1", "electrical", "mep", "cable tray", "L1", "L1|0_0",
        _box((0.3, 0.3, 0.3), (0.15, 0.0, 0.0)),  # overlaps D1 by 150mm in x
    )
    f1 = Element(
        "F1", "fire", "mep", "sprinkler main leg A", "L1", "L1|5_0",
        _box((0.2, 0.2, 0.2), (5.0, 0.0, 0.0)),
    )
    f2 = Element(
        "F2", "chilled_water", "mep", "chilled water pipe", "L1", "L1|5_0",
        _box((0.2, 0.2, 0.2), (5.0, 0.4, 0.0)),  # 200mm gap from F1
    )
    g1 = Element(
        "G1", "drainage_storm", "mep", "storm drain run", "L2", "L2|9_9",
        _box((0.2, 0.2, 0.2), (20.0, 0.0, 0.0)), is_gravity=True,
    )
    w1 = Element(
        "W1", "structure", "structural", "load-bearing wall", "L1", "L1|9_9",
        _box((0.1, 4.0, 3.0), (20.0, 20.0, 0.0)),
    )
    return [d1, e1, f1, f2, g1, w1]


# The one clearance rule this test plants: fire vs chilled_water, 300mm,
# unordered pair -- mirrors what clearance_rules.py would load from a
# sourced rule table, without needing that module or a JSON file here.
CLEARANCE_PAIR = {"fire", "chilled_water"}
REQUIRED_GAP_M = 0.3
RULE_ID = "TEST-FIRE-CHW-300"


def _judge_all_pairs(elements: list[Element]):
    """B1: geometry_engine.judge_pair over every element pair.

    On a real model this list would already be filtered by the padded AABB
    pre-filter; with six elements there is nothing to gain by pre-filtering,
    so every pair is judged directly, which is a strict superset of what
    the pre-filter would admit.
    """
    findings = []
    for a, b in itertools.combinations(elements, 2):
        governed = {a.system, b.system} == CLEARANCE_PAIR
        findings.append(
            judge_pair(
                a.global_id, b.global_id, a.mesh, b.mesh,
                required_clearance_m=REQUIRED_GAP_M if governed else None,
                rule_id=RULE_ID if governed else None,
                category_a=a.system, category_b=b.system,
            )
        )
    return findings


def test_b1_plants_one_real_clash_and_one_real_clearance_violation():
    """Sanity check on the constructed geometry itself, before any block
    under test runs -- if this fails, the fixture is wrong, not the
    pipeline."""
    elements = _build_elements()
    findings = _judge_all_pairs(elements)

    clashes = [f for f in findings if f.kind == "clash"]
    clearances = [f for f in findings if f.kind == "clearance"]

    assert any({f.element_a, f.element_b} == {"D1", "E1"} for f in clashes), (
        "D1/E1 must be judged a real overlap, not a bounding-box false positive"
    )
    assert any({f.element_a, f.element_b} == {"F1", "F2"} for f in clearances), (
        "F1/F2 (200mm apart, 300mm rule) must be judged a real clearance violation"
    )


def test_full_pipeline_b1_b3_b4_b7_scores_a_nonzero_resolution():
    """The regression test proper: B1 -> B3 -> B4 -> B7, real entry points,
    real geometry that actually needs fixing.

    A zero in the final assertions here means the ids drifted apart again
    -- the exact incident this test suite exists to catch: clash_triage
    once derived "A__B" while version_diff derived "A::B" for the identical
    pair, both modules' unit tests passed, and score_proposals silently
    reported 0.0 forever because no proposal's clash_id could ever match a
    diff_versions "resolved" entry.
    """
    elements = _build_elements()
    by_id = {e.global_id: e for e in elements}

    # B1.
    findings_v1 = _judge_all_pairs(elements)

    # B3: clash_triage.triage -- dedupe, classify, rank into a real queue.
    triage_result = clash_triage.triage(findings_v1, by_id)
    assert triage_result.queue, "triage produced an empty queue on planted findings"

    top = triage_result.queue[0]
    # order.yaml resolves ventilation/electrical (D1/E1's systems) before
    # fire/chilled_water (F1/F2's) -- pinning this lets a reader see exactly
    # which planted finding B4 is about to act on.
    assert {top.element_a, top.element_b} == {"D1", "E1"}

    # B4: clash_resolver.resolve -- a checked, sourced proposal for the top
    # queue item. required_gap_mm=150 is chosen deliberately: the FIRST
    # candidate offset (toward E1) still overlaps and must be rejected, and
    # only the SECOND (away from E1) actually clears it -- proving resolve()
    # re-checks its own candidate instead of returning the first
    # geometrically-free-sounding one.
    moved_id = top.element_a
    moved_element = by_id[moved_id]
    neighbours = [e for gid, e in by_id.items() if gid != moved_id]

    proposal = clash_resolver.resolve(
        top, moved_element, neighbours,
        required_gap_mm=150.0,
        rule_ids=["TEST-CLEARANCE-RULE"],
        clause_text="TEST CLAUSE 9.1: maintain clearance around ductwork",
    )
    assert proposal.status == clash_resolver.STATUS_PROPOSED, (
        f"expected a proposed move, got {proposal.status}: {proposal.rejected}"
    )
    assert any(abs(v) > 0 for v in proposal.move_vector_mm)

    # Simulate v2: apply the proposal's move to a COPY of the moved
    # element's mesh. Applying a move for real is model_clone's job (B6,
    # against a clone, on disk); this inline translation stays inside the
    # contract of the four blocks actually under test here.
    moved_mesh = moved_element.mesh.copy()
    moved_mesh.apply_translation([v / 1000.0 for v in proposal.move_vector_mm])
    elements_v2 = [
        Element(
            e.global_id, e.system, e.discipline, e.name, e.level, e.zone_key,
            moved_mesh if e.global_id == moved_id else e.mesh,
            is_gravity=e.is_gravity,
        )
        for e in elements
    ]

    # Re-judge every pair against the moved geometry.
    findings_v2 = _judge_all_pairs(elements_v2)

    # B7: version_diff.diff_versions, then score_proposals against the
    # proposal actually made.
    diff = version_diff.diff_versions(findings_v1, findings_v2)
    resolved_pairs = {(e["element_a"], e["element_b"]) for e in diff["resolved"]}
    assert ("D1", "E1") in resolved_pairs, (
        "the planted D1/E1 clash must land in version_diff's 'resolved' "
        f"bucket after the move; diff was: {diff}"
    )

    score = version_diff.score_proposals([proposal], diff)
    assert score["proposed"] > 0, (
        "no proposal was even counted -- check score_proposals's own counting, "
        "not the id matching"
    )
    assert score["resolved"] > 0, (
        "ZERO HERE MEANS THE IDS DRIFTED APART AGAIN: the clash_id "
        f"clash_resolver put on its proposal ({proposal.clash_id!r}) never "
        "matched an entry in diff_versions' 'resolved' bucket "
        f"({[e['clash_id'] for e in diff['resolved']]!r}). That is exactly "
        "the 'A__B' vs 'A::B' incident this test suite exists to prevent -- "
        "check that clash_triage and version_diff still agree on identity.py's "
        "canonical clash_id."
    )
    assert score["rate"] > 0, "rate is resolved/proposed -- cannot be 0 when resolved > 0 and proposed > 0"


def test_clash_triage_queue_item_clash_id_matches_version_diff_exactly():
    """The direct pin on the original bug: clash_triage's own clash_id for a
    queued item must be BYTE-IDENTICAL to what version_diff derives for the
    same pair -- not "equal after normalising separators", identical.
    """
    elements = _build_elements()
    by_id = {e.global_id: e for e in elements}
    findings = _judge_all_pairs(elements)

    result = clash_triage.triage(findings, by_id)
    assert result.queue, "need at least one queued item to compare ids on"

    for item in result.queue:
        expected = version_diff._clash_id(
            version_diff._pair_key(item.element_a, item.element_b)
        )
        assert item.clash_id == expected, (
            f"clash_triage produced {item.clash_id!r} for "
            f"({item.element_a}, {item.element_b}) but version_diff would "
            f"produce {expected!r} for the identical pair -- this is the "
            "exact id-drift that made score_proposals report 0.0 forever"
        )
