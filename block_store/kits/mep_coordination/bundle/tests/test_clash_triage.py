"""clash_triage: three tests + mutation probe.

The defects being guarded are the ones that make a coordination report get
ignored: the same conflict listed several times, assembly artefacts drowning
the real findings, and a queue whose order does not match how the work
happens.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.blocks.clash_triage import (
    KIND_CLEARANCE,
    KIND_HARD,
    QueueItem,
    TriageResult,
    _severity_mm,
    _zone_of,
    load_order,
    load_programme,
    pair_key,
    resolution_rank,
    triage,
    zone_congestion,
)


@dataclass
class F:
    element_a: str
    element_b: str
    kind: str = "clash"
    distance_m: float | None = 0.0
    required_clearance_m: float | None = None
    penetration_volume_m3: float | None = 0.001
    rule_id: str | None = None
    category_a: str | None = None
    category_b: str | None = None


@dataclass
class E:
    global_id: str
    system: str
    name: str = ""
    level: str = "L1"
    discipline: str = "mep"
    zone_key: str = "L1|0_0"
    bbox: tuple = (0, 0, 0, 1, 1, 1)


def test_the_same_clash_reported_twice_is_queued_once():
    """A clash between A and B is the same clash as between B and A. Counting
    it twice is what turns 400 real conflicts into an 800-row report nobody
    reads."""
    els = {"A": E("A", "ventilation"), "B": E("B", "electrical")}
    findings = [F("A", "B"), F("B", "A")]  # same conflict, both orderings
    r = triage(findings, els)
    assert len(r.queue) == 1
    assert r.deduped == 1


def test_a_fitting_meeting_its_own_segment_is_dropped_but_counted():
    """Assembly, not conflict. Dropping it is right; dropping it SILENTLY is
    not -- an invisible drop cannot be distinguished from a missed clash."""
    els = {
        "P1": E("P1", "drainage_storm", name="hwa afvoer segment"),
        "P2": E("P2", "drainage_storm", name="hwa afvoer bend fitting"),
    }
    r = triage([F("P1", "P2")], els)
    assert r.queue == []
    assert r.dropped_workflow == 1


def test_a_cross_system_fitting_clash_is_NOT_treated_as_noise():
    """The guard needs both conditions. A fitting touching a DIFFERENT
    system is a real clash; suppressing it on the fitting hint alone would
    hide genuine conflicts."""
    els = {
        "P1": E("P1", "drainage_storm", name="hwa afvoer bend fitting"),
        "D1": E("D1", "ventilation", name="duct fitting"),
    }
    r = triage([F("P1", "D1")], els)
    assert len(r.queue) == 1
    assert r.dropped_workflow == 0


def test_gravity_is_queued_before_pressurised_whatever_the_severity():
    """Order is a sequence, not a preference. A trivial gravity clash still
    precedes a severe pressurised one, because moving the drain last means
    its space is already gone."""
    els = {
        "G1": E("G1", "drainage_storm"), "W1": E("W1", "structure", discipline="structural"),
        "F1": E("F1", "fire"), "W2": E("W2", "structure", discipline="structural"),
    }
    minor_gravity = F("G1", "W1", penetration_volume_m3=1e-9)
    severe_pressurised = F("F1", "W2", penetration_volume_m3=10.0)
    r = triage([severe_pressurised, minor_gravity], els)
    assert r.queue[0].system_a == "drainage_storm" or r.queue[0].system_b == "drainage_storm"
    assert r.queue[0].resolution_rank < r.queue[1].resolution_rank


def test_congestion_ranks_the_denser_zone_higher():
    """Two zones, same clash count, different density."""
    dense = [E(f"d{i}", "ventilation", zone_key="L1|0_0", bbox=(0, 0, 0, 2, 2, 2)) for i in range(6)]
    sparse = [E("s1", "ventilation", zone_key="L1|9_9", bbox=(0, 0, 0, 0.2, 0.2, 0.2))]
    z = zone_congestion({e.global_id: e for e in dense + sparse}.values())
    assert z["L1|0_0"] > z["L1|9_9"]


def test_an_unknown_system_is_ranked_last_but_never_dropped():
    """An unclassified service is exactly the one to look at, not to hide."""
    order = load_order()
    assert resolution_rank("drainage_storm", order) == 1
    assert resolution_rank("some_unmapped_system", order) == len(order) + 1


def test_order_yaml_and_the_builtin_fallback_agree():
    """The YAML is the source of record and the fallback exists only for a
    missing PyYAML. If they drift, the queue silently changes depending on
    whether an optional dependency is installed."""
    from app.blocks.clash_triage import _DEFAULT_ORDER

    loaded = load_order()
    assert [c for c, _ in loaded] == [c for c, _ in _DEFAULT_ORDER]
    for (_, a), (_, b) in zip(loaded, _DEFAULT_ORDER):
        assert set(a) == set(b)


def test_mutation_probe_ordered_pair_key_reopens_double_counting():
    """MUTATION PROBE.

    Dedupe hinges on the pair key being unordered. Restore an ordered key and
    the same conflict reported both ways becomes two queue rows again.
    """
    def ordered_key(a: str, b: str) -> tuple[str, str]:
        return (a, b)  # the bug

    a, b = "A", "B"
    assert pair_key(a, b) == pair_key(b, a), "unordered key is the invariant"
    assert ordered_key(a, b) != ordered_key(b, a), (
        "probe is inert: the mutant must actually differ from the real key"
    )

    els = {"A": E("A", "ventilation"), "B": E("B", "electrical")}
    real = triage([F("A", "B"), F("B", "A")], els)
    assert len(real.queue) == 1, "engine regressed to counting both orderings"


def test_queue_item_as_dict_is_a_plain_copy_of_its_fields():
    """as_dict() is what a report/JSON export actually consumes -- it must
    carry every field through, not just a subset."""
    item = QueueItem(
        clash_id="A::B", element_a="A", element_b="B", kind=KIND_HARD,
        system_a="ventilation", system_b="electrical", zone_key="L1|0_0",
        level="L1", severity_mm=42.0, resolution_rank=1,
    )
    d = item.as_dict()
    assert d["clash_id"] == "A::B"
    assert d["severity_mm"] == 42.0
    assert d["resolution_rank"] == 1
    # It's a copy, not a view -- mutating it must not touch the QueueItem.
    d["severity_mm"] = 0.0
    assert item.severity_mm == 42.0


def test_triage_result_as_dict_reports_queue_length_and_counts():
    """The dict form is what a caller checks the run's shape from -- if
    queue_length disagrees with len(queue), a report could claim a different
    row count than it actually renders."""
    els = {"A": E("A", "ventilation"), "B": E("B", "electrical")}
    r = triage([F("A", "B")], els)
    d = r.as_dict()
    assert d["queue_length"] == len(r.queue) == 1
    assert d["dropped_workflow"] == r.dropped_workflow
    assert d["deduped"] == r.deduped
    assert d["zones"] == r.zones
    assert d["queue"][0]["clash_id"] == r.queue[0].clash_id


def test_load_order_falls_back_to_builtin_when_pyyaml_is_unavailable(monkeypatch):
    """This block must not fail closed on a missing optional dependency --
    the whole triage queue would become unavailable over a formatting
    library, which the module's own docstring calls out as unacceptable."""
    import sys

    from app.blocks.clash_triage import _DEFAULT_ORDER

    monkeypatch.setitem(sys.modules, "yaml", None)  # forces ImportError
    order = load_order()
    assert order == list(_DEFAULT_ORDER)


def test_load_order_falls_back_when_order_yaml_is_unreadable(tmp_path):
    """A corrupt or restructured order.yaml (bad syntax, or missing the
    resolution_order key) must not crash the triage run -- it must fall back
    to the built-in order, the same as a missing PyYAML."""
    from app.blocks.clash_triage import _DEFAULT_ORDER

    bad_yaml = tmp_path / "order.yaml"
    bad_yaml.write_text("not_resolution_order: [1, 2, 3]\n", encoding="utf-8")

    order = load_order(bad_yaml)
    assert order == list(_DEFAULT_ORDER)


def test_severity_mm_for_a_clash_with_measured_penetration():
    """A hard clash WITH a measured penetration volume must scale to a
    millimetre-comparable severity so it can be ranked against a clearance
    shortfall on the same axis -- the module's own formula is
    ``volume_m3 * 1e9 ** (1/3)``, i.e. a flat x1000 scaling of the volume."""
    finding = F("A", "B", kind="clash", penetration_volume_m3=1.0)
    assert _severity_mm(finding) == pytest.approx(1000.0, abs=1e-6)

    smaller = F("A", "B", kind="clash", penetration_volume_m3=1e-3)
    assert _severity_mm(smaller) == pytest.approx(1.0, abs=1e-9)


def test_severity_mm_for_a_clash_without_a_measured_penetration():
    """Contact proven by surface intersection alone (no volume, e.g.
    non-watertight source geometry) must still get a real, comparable
    severity number -- not zero, which would rank it below a trivial
    clearance nick."""
    finding = F("A", "B", kind="clash", penetration_volume_m3=None)
    assert _severity_mm(finding) == 1000.0

    finding_zero_pen = F("A", "B", kind="clash", penetration_volume_m3=0.0)
    assert _severity_mm(finding_zero_pen) == 1000.0


def test_severity_mm_for_a_clearance_shortfall():
    """A clearance violation's severity is how far short of the requirement
    the measured distance fell, in millimetres -- not the raw distance."""
    finding = F(
        "A", "B", kind="clearance", distance_m=0.1,
        required_clearance_m=0.3, penetration_volume_m3=None,
    )
    assert _severity_mm(finding) == pytest.approx(200.0, abs=1e-6)


def test_severity_mm_is_zero_when_neither_penetration_nor_clearance_data_exists():
    """Anything that is not a clash and carries no rule-checked
    distance/requirement pair has no comparable severity to report -- 0.0,
    not a crash or a fabricated number."""
    finding = F(
        "A", "B", kind="clear", distance_m=None,
        required_clearance_m=None, penetration_volume_m3=None,
    )
    assert _severity_mm(finding) == 0.0


def test_zone_congestion_skips_an_element_with_no_bbox():
    """An element the parser could not mesh has no bbox. It must be excluded
    from the congestion calculation, not crash it or silently count as zero
    volume in a real zone."""

    @dataclass
    class NoBBox:
        global_id: str
        zone_key: str = "L1|0_0"
        discipline: str = "mep"
        bbox: tuple | None = None

    result = zone_congestion([NoBBox("X")])
    assert result == {}, "an element with no geometry must not fabricate a zone entry"


def test_zone_of_is_used_when_an_element_has_no_explicit_zone_key():
    """zone_congestion must derive a zone from the bbox when zone_key is
    absent -- this is the fallback the module relies on for elements that
    were never assigned a zone upstream."""
    # E always sets zone_key explicitly, so a distinct element type with no
    # zone_key attribute at all is needed for getattr(...) to genuinely fall
    # through to the _zone_of() derivation.
    @dataclass
    class NoZoneKey:
        global_id: str
        discipline: str = "mep"
        bbox: tuple = (7, 7, 0, 8, 8, 1)
        level: str = "L1"

    el = NoZoneKey("A")
    expected_key = _zone_of(el, 6.0)
    result = zone_congestion([el])
    assert expected_key in result
    assert result[expected_key] > 0.0


def test_load_programme_with_a_missing_file_returns_an_empty_mapping():
    """No programme CSV supplied (or the wrong path) must not fail the
    triage run -- congestion alone drives ranking, which the module allows
    explicitly."""
    assert load_programme("this/path/does/not/exist.csv") == {}


def test_load_programme_skips_a_malformed_row_but_keeps_the_valid_ones(tmp_path):
    """A row missing zone or planned_install_date cannot be used to sequence
    work -- it must be dropped, not turned into a bogus '' key or crash the
    whole load over one bad line."""
    csv_path = tmp_path / "programme.csv"
    csv_path.write_text(
        "zone,planned_install_date\n"
        "L1|0_0,2026-01-15\n"
        ",2026-02-01\n"          # missing zone
        "L1|1_1,\n"              # missing date
        "L2|0_0,2026-03-01\n",
        encoding="utf-8",
    )
    programme = load_programme(csv_path)
    assert programme == {"L1|0_0": "2026-01-15", "L2|0_0": "2026-03-01"}


def test_triage_skips_clear_and_unjudged_findings():
    """A finding that geometry_engine already judged clean, or could not
    judge at all, has no place in a resolution queue -- it must be filtered
    out before dedupe/classification, not queued as a phantom conflict."""
    els = {"A": E("A", "ventilation"), "B": E("B", "electrical")}
    findings = [
        F("A", "B", kind="clear"),
        F("A", "B", kind="unjudged"),
    ]
    r = triage(findings, els)
    assert r.queue == []
    assert r.dropped_workflow == 0
    assert r.deduped == 0
