"""connectivity: the discriminating test, plus topology and a mutation probe.

F5 was: connected pipe segments in a single-discipline run read as hard
clashes, because the old filter keyed on fitting NAMES. The fix must exclude
joints WITHOUT excusing a real conflict — so the central test asserts both
directions at once. A filter that passes the joint half by breaking the clash
half fails here, which is the whole point.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

trimesh = pytest.importorskip("trimesh", reason="geometry backend not installed")

from app.blocks.connectivity import (  # noqa: E402
    REASON_PORT,
    REASON_TANGENT,
    ConnectivityGraph,
    classify_findings,
    joint_reason,
)
from app.blocks.geometry_engine import exact_backend_available, judge_pair  # noqa: E402


@dataclass
class El:
    global_id: str
    system: str = "drainage_foul"
    discipline: str = "mep"
    name: str = ""
    mesh: object = None


def _pipe(length=2.0, at=(0.0, 0.0, 0.0), r=0.1):
    """A pipe as a cylinder along X, positioned by its centre."""
    m = trimesh.creation.cylinder(radius=r, height=length, sections=24)
    m.apply_transform(trimesh.transformations.rotation_matrix(1.5707963, (0, 1, 0)))
    m.apply_translation(at)
    return m


def test_a_joint_is_excluded_AND_a_real_interpenetration_still_reads_hard():
    """THE discriminating test. Both assertions, one test, on purpose.

    Case A — a JOINT: two same-system pipes meeting end to end. Their surfaces
    touch, so the engine calls it a clash, but the enclosed volume is zero.
    That must be excluded as a connected joint.

    Case B — a REAL clash: a pipe driven THROUGH another, no port link, same
    system. The solids enclose real volume. That must still read hard.

    A filter that passes A by relaxing until B also passes has removed the
    only thing this kit is for.
    """
    if not exact_backend_available():
        pytest.skip("exact boolean backend required to measure penetration volume")

    # A: end-to-end. Two 2 m pipes whose ends meet at x = 1.0.
    a1 = El("A1", name="sewer pipe", mesh=_pipe(at=(0.0, 0, 0)))
    a2 = El("A2", name="sewer pipe", mesh=_pipe(at=(2.0, 0, 0)))
    fa = judge_pair("A1", "A2", a1.mesh, a2.mesh)
    reason_a = joint_reason(a1, a2, fa.penetration_volume_m3)

    # B: crossing. A pipe through a pipe, perpendicular, sharing the same space.
    b1 = El("B1", name="sewer pipe", mesh=_pipe(at=(0.0, 0, 0)))
    crossing = trimesh.creation.cylinder(radius=0.1, height=2.0, sections=24)
    crossing.apply_translation((0.0, 0, 0))          # along Z, through B1
    b2 = El("B2", name="sewer pipe", mesh=crossing)
    fb = judge_pair("B1", "B2", b1.mesh, b2.mesh)
    reason_b = joint_reason(b1, b2, fb.penetration_volume_m3)

    # Case A is a joint.
    assert reason_a == REASON_TANGENT, (
        f"end-to-end joint not excluded (penetration={fa.penetration_volume_m3})"
    )
    # Case B is NOT, and this is the assertion a lazy filter breaks.
    assert fb.kind == "clash", "the crossing pipes must be detected as a clash at all"
    assert (fb.penetration_volume_m3 or 0) > 0, "a real crossing must enclose volume"
    assert reason_b is None, (
        "a pipe driven through another pipe was excused as a joint -- the "
        "filter has been relaxed until it hides real clashes"
    )


def test_topology_outranks_geometry_when_the_model_actually_says_so():
    """Where ports exist, the model's own statement wins. Two elements the
    model links are a joint even if the measurement is ambiguous."""
    g = ConnectivityGraph(edges={frozenset(("P1", "P2"))}, connections_seen=1)
    a, b = El("P1"), El("P2")
    assert g.available is True
    assert joint_reason(a, b, penetration_volume_m3=0.5, graph=g) == REASON_PORT


def test_an_empty_graph_is_not_proof_that_nothing_is_connected():
    """Both available fixtures carry ZERO ports. Treating an empty graph as
    'nothing is joined' would flag every joint in any model that omits port
    data -- which is most of them."""
    g = ConnectivityGraph()
    assert g.available is False
    a, b = El("P1"), El("P2")
    # Falls through to the measurement rather than asserting non-connection.
    assert joint_reason(a, b, penetration_volume_m3=0.0, graph=g) == REASON_TANGENT


def test_cross_system_contact_is_never_a_joint():
    """A duct touching a drain is a real clash however shallow. The system
    check is what stops the fallback becoming a blanket amnesty."""
    a = El("A", system="drainage_foul")
    b = El("B", system="ventilation")
    assert joint_reason(a, b, penetration_volume_m3=0.0) is None


def test_an_unmeasured_zero_excludes_nothing():
    """Without the exact backend a zero is not a measurement, so it cannot
    justify an exclusion."""
    a, b = El("A"), El("B")
    assert joint_reason(a, b, 0.0, exact_backend=False) is None
    assert joint_reason(a, b, None) is None


def test_joints_are_returned_and_counted_never_silently_dropped():
    """A joint that vanishes is indistinguishable from a missed clash."""
    @dataclass
    class F:
        element_a: str
        element_b: str
        kind: str = "clash"
        penetration_volume_m3: float | None = 0.0
        note: str | None = None

    els = {"A": El("A"), "B": El("B")}
    real, joints = classify_findings([F("A", "B")], els)
    assert real == []
    assert len(joints) == 1
    assert joints[0].kind == "joint"
    assert joints[0].note == REASON_TANGENT


def test_mutation_probe_widening_the_touch_floor_starts_hiding_real_clashes():
    """MUTATION PROBE.

    TOUCH_VOLUME_M3 is a noise floor, not a tolerance. Widen it to something a
    person might call 'small' and a genuine interpenetration is excused. The
    probe proves the floor is doing real work.
    """
    import app.blocks.connectivity as conn

    a, b = El("A"), El("B")
    real_overlap = 0.002          # 2 litres of shared volume: a real conflict

    assert joint_reason(a, b, real_overlap) is None, "baseline: a real overlap is a clash"

    original = conn.TOUCH_VOLUME_M3
    try:
        conn.TOUCH_VOLUME_M3 = 0.01          # the mutant: a 'small' tolerance
        assert joint_reason(a, b, real_overlap) == REASON_TANGENT, (
            "probe inert: widening the floor should have excused the overlap"
        )
    finally:
        conn.TOUCH_VOLUME_M3 = original
    assert joint_reason(a, b, real_overlap) is None, "floor not restored"
