"""geometry_engine: the three tests + mutation probe required per block.

These use constructed solids rather than an IFC file on purpose. The defect
being guarded against is a GEOMETRIC one -- bounding boxes calling two
non-touching services a clash -- and a box-vs-mesh disagreement is provable
without any model. A model-level test cannot isolate it, because a real model
mixes the geometry question with parser questions.
"""
from __future__ import annotations

import pytest

trimesh = pytest.importorskip("trimesh", reason="geometry backend not installed")

import numpy as np

import app.blocks.geometry_engine as geometry_engine
from app.blocks.geometry_engine import (  # noqa: E402
    KIND_CLASH,
    KIND_CLEAR,
    KIND_CLEARANCE,
    KIND_UNJUDGED,
    METHOD_DISTANCE,
    METHOD_EXACT,
    METHOD_SURFACE,
    Finding,
    GeometryResult,
    aabb_overlaps,
    exact_backend_available,
    judge_pair,
)
from app.blocks.geometry_engine import _mesh_pair_measure  # noqa: E402


def _box(size=(1, 1, 1), at=(0, 0, 0)):
    m = trimesh.creation.box(extents=size)
    m.apply_translation(at)
    return m


def test_interpenetrating_solids_are_a_clash_and_cite_no_rule():
    """A hard clash is a clash under every rule, so it must not depend on
    one being supplied -- and must not invent a citation."""
    a, b = _box(), _box(at=(0.5, 0, 0))
    f = judge_pair("A", "B", a, b)
    assert f.kind == KIND_CLASH
    assert f.rule_id is None
    if exact_backend_available():
        assert f.method == METHOD_EXACT
        assert f.penetration_volume_m3 == pytest.approx(0.5, abs=1e-3)


def test_close_but_not_touching_is_a_clearance_violation_not_a_clash():
    """The distinction the whole kit turns on. 300mm apart, 500mm required:
    nothing touches, but it cannot be built, maintained or insulated."""
    a, b = _box(), _box(at=(1.3, 0, 0))  # 0.3 m gap
    f = judge_pair("A", "B", a, b, required_clearance_m=0.5, rule_id="SBC-501-X")
    assert f.kind == KIND_CLEARANCE
    assert f.distance_m == pytest.approx(0.3, abs=1e-3)
    assert f.rule_id == "SBC-501-X"          # a clearance finding MUST cite
    assert f.required_clearance_m == 0.5


def test_far_apart_is_clear_and_the_same_pair_flips_when_the_rule_tightens():
    """Same geometry, different rule -> different verdict. Proves the rule is
    doing the judging, not a hardcoded threshold hiding in the engine."""
    a, b = _box(), _box(at=(3, 0, 0))  # 2.0 m gap
    assert judge_pair("A", "B", a, b, required_clearance_m=0.5).kind == KIND_CLEAR
    tightened = judge_pair("A", "B", a, b, required_clearance_m=2.5, rule_id="R")
    assert tightened.kind == KIND_CLEARANCE


def test_the_aabb_prefilter_must_pad_by_the_clearance_or_it_hides_violations():
    """The pre-filter's own failure mode. Two boxes 0.3 m apart do NOT
    overlap, so an unpadded filter discards the pair -- and the clearance
    violation in the test above would never be measured. Padding by the
    largest rule is what keeps the filter honest."""
    a = (0, 0, 0, 1, 1, 1)
    b = (1.3, 0, 0, 2.3, 1, 1)
    assert aabb_overlaps(a, b) is False           # unpadded: pair dropped
    assert aabb_overlaps(a, b, pad=0.5) is True   # padded: pair survives


def test_no_geometry_is_reported_unjudged_never_clean():
    """Silence is not a pass. An element the parser could not mesh must be
    visibly unjudged, or a coordination report claims a clean zone it never
    actually looked at."""
    class Unmeshable:
        bounds = None
        vertices = None
        is_watertight = False

        def intersection(self, other):
            raise RuntimeError("no geometry")

        def contains(self, pts):
            raise RuntimeError("no geometry")

    f = judge_pair("A", "B", Unmeshable(), Unmeshable())
    assert f.kind == KIND_UNJUDGED
    assert f.kind != KIND_CLEAR


def test_mutation_probe_bounding_box_verdict_reopens_the_false_positives():
    """MUTATION PROBE.

    The replaced behaviour was "boxes overlap => clash". Expressed directly so
    the probe fails loudly if anyone restores it: two diagonal services whose
    BOXES overlap while the SOLIDS are metres apart. Under the old rule this
    pair is a clash; under this engine it is clear. If those two answers ever
    agree, the engine has regressed to a bounding-box test.
    """
    import numpy as np

    def _diagonal_bar(offset=(0, 0, 0)):
        """A 4 m service running at 45 deg -- the shape an AABB describes worst."""
        m = trimesh.creation.box(extents=(4, 0.2, 0.2))
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 4, (0, 0, 1)))
        m.apply_translation(offset)
        return m

    # Two parallel diagonal services running side by side, 507 mm apart. This
    # is not a contrived shape: it is a cable tray beside a pipe on the same
    # rack. Their upright boxes overlap heavily; the solids never touch.
    mesh_a = _diagonal_bar()
    mesh_b = _diagonal_bar((-0.5, 0.5, 0))

    old_rule_says_clash = aabb_overlaps(mesh_a.bounds.flatten(), mesh_b.bounds.flatten())
    new_verdict = judge_pair("A", "B", mesh_a, mesh_b, required_clearance_m=0.1)

    assert old_rule_says_clash is True, (
        "fixture no longer exercises the defect: the boxes must overlap for "
        "this probe to mean anything"
    )
    assert new_verdict.kind == KIND_CLEAR, (
        "engine agreed with the bounding-box verdict -- the false positive is back"
    )


def _open_box(size=(1, 1, 1), at=(0, 0, 0)):
    """A box missing one face -- genuinely non-watertight, not a stand-in.

    Used to exercise the code path a real, poorly-formed or non-manifold IFC
    export takes: exact boolean intersection cannot be trusted on it, so the
    engine must fall back to surface intersection / distance instead of
    raising or silently mis-measuring.
    """
    m = trimesh.creation.box(extents=size)
    mask = np.ones(len(m.faces), dtype=bool)
    mask[-1] = False
    m.update_faces(mask)
    m.apply_translation(at)
    return m


def test_geometry_result_as_dict_reports_findings_and_counts():
    """The result object is what a caller (and a report) actually consumes.
    If as_dict() miscounts or drops a finding, every downstream consumer of
    this block inherits the mistake silently."""
    findings = [
        Finding("A", "B", KIND_CLASH, METHOD_EXACT, penetration_volume_m3=0.2),
        Finding("C", "D", KIND_CLEARANCE, METHOD_DISTANCE, distance_m=0.1),
        Finding("E", "F", KIND_UNJUDGED, "no_geometry"),
    ]
    result = GeometryResult(
        findings=findings,
        pairs_tested=3,
        pairs_prefiltered=1,
        elements_without_geometry=["E"],
        exact_backend_available=True,
    )
    d = result.as_dict()
    assert d["pairs_tested"] == 3
    assert d["pairs_prefiltered"] == 1
    assert d["elements_without_geometry"] == ["E"]
    assert d["exact_backend_available"] is True
    assert d["counts"] == {KIND_CLASH: 1, KIND_CLEARANCE: 1, KIND_UNJUDGED: 1}
    assert len(d["findings"]) == 3
    assert d["findings"][0]["element_a"] == "A"


def test_exact_backend_unavailable_when_manifold3d_cannot_be_imported(monkeypatch):
    """If manifold3d is missing, the engine must degrade to surface
    intersection rather than crash or silently claim exactness. A consumer
    ranking findings by confidence needs this to be honest."""
    import sys

    monkeypatch.setitem(sys.modules, "manifold3d", None)  # forces ImportError
    assert exact_backend_available() is False


def test_exact_backend_unavailable_when_trimesh_cannot_be_imported(monkeypatch):
    """Same guarantee, the other dependency: manifold3d alone is not enough
    to claim exact boolean intersection -- trimesh drives the actual mesh
    operations."""
    import sys

    assert "manifold3d" not in sys.modules or sys.modules["manifold3d"] is not None
    monkeypatch.setitem(sys.modules, "trimesh", None)  # forces ImportError
    assert exact_backend_available() is False


def test_mesh_pair_measure_falls_back_to_surface_intersection_when_backend_unavailable(monkeypatch):
    """When the exact boolean backend is unavailable, _mesh_pair_measure must
    skip the boolean path entirely (not attempt it and fail) and still prove
    contact via surface intersection for two genuinely touching solids."""
    monkeypatch.setattr(geometry_engine, "exact_backend_available", lambda: False)

    b = trimesh.creation.box(extents=(1, 1, 1))
    a = _open_box((0.6, 0.6, 0.6), (0.3, 0, 0))
    assert not a.is_watertight, "fixture must actually be non-watertight"

    # Argument order matters here: _surfaces_intersect checks
    # mesh_b.contains(mesh_a.vertices) FIRST -- passing the watertight box as
    # mesh_b is what exercises that primary (not the fallback) containment
    # check.
    method, penetration, distance = _mesh_pair_measure(a, b)
    assert method == METHOD_SURFACE
    assert penetration is None
    assert distance == 0.0


def test_mesh_pair_measure_falls_back_to_distance_when_surfaces_do_not_touch(monkeypatch):
    """Backend unavailable AND the solids do not actually touch: the engine
    must still measure a real separation distance rather than reporting a
    false contact or giving up."""
    monkeypatch.setattr(geometry_engine, "exact_backend_available", lambda: False)

    a = _open_box((0.6, 0.6, 0.6), (0, 0, 0))
    b = _open_box((0.6, 0.6, 0.6), (5, 0, 0))
    assert not aabb_overlaps(a.bounds.flatten(), b.bounds.flatten())

    method, penetration, distance = _mesh_pair_measure(a, b)
    assert method == METHOD_DISTANCE
    assert penetration == 0.0
    assert distance is not None and distance > 4.0


def test_mesh_pair_measure_reports_no_intersection_when_aabbs_overlap_but_solids_do_not():
    """The exact scenario this block exists for, seen from inside
    _surfaces_intersect: two diagonal bars whose boxes overlap but whose
    real surfaces never cross. Both containment checks must come back False
    and the method must fall through to a distance measurement, not a false
    contact."""
    import app.blocks.geometry_engine as ge

    def _open_diagonal(offset):
        m = trimesh.creation.box(extents=(4, 0.2, 0.2))
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 4, (0, 0, 1)))
        mask = np.ones(len(m.faces), dtype=bool)
        mask[-1] = False
        m.update_faces(mask)
        m.apply_translation(offset)
        return m

    a = _open_diagonal((0, 0, 0))
    b = _open_diagonal((-0.5, 0.5, 0))
    assert not a.is_watertight and not b.is_watertight
    assert aabb_overlaps(a.bounds.flatten(), b.bounds.flatten()) is True
    assert ge._surfaces_intersect(a, b) is False, (
        "boxes overlap but the real diagonal solids do not -- contains() must "
        "say so in both directions, not just one"
    )


def test_mesh_pair_measure_falls_back_when_the_boolean_backend_itself_raises():
    """A watertight-looking mesh can still make the boolean backend blow up
    (manifold3d is not bulletproof on every real IFC export). The engine
    must catch that and fall back to a weaker method instead of propagating
    the crash into a coordination run."""

    class ForcedWatertightBoom:
        """Claims watertight (so the exact path is attempted) but its
        boolean intersection genuinely raises, simulating a manifold3d
        failure on a degenerate mesh."""

        def __init__(self, mesh):
            self._mesh = mesh

        @property
        def is_watertight(self):
            return True

        def intersection(self, other):
            raise RuntimeError("boolean backend exploded")

        def __getattr__(self, name):
            return getattr(self._mesh, name)

    real_a = trimesh.creation.box(extents=(1, 1, 1))
    real_b = trimesh.creation.box(extents=(0.6, 0.6, 0.6))
    real_b.apply_translation((0.3, 0, 0))
    boom = ForcedWatertightBoom(real_a)

    assert exact_backend_available() is True, "this test needs the real backend present"
    method, penetration, distance = _mesh_pair_measure(boom, real_b)
    # The exception in intersection() must be swallowed and the pair still
    # judged -- via surface intersection, since the meshes genuinely overlap.
    assert method == METHOD_SURFACE
    assert distance == 0.0
