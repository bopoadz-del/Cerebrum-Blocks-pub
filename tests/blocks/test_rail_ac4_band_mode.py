"""Rail AC4: the kit_engine QUALIFIER band, rail's derivation guards and the
datacentre chiller-incident regression -- all on synthetic data.

A qualifier band is the general engine mode in which a figure's allowed range
comes from its OWN qualifiers (``min_from`` / ``max_from``) and the value
checked is the ``subject`` the question is about. Rail declares it as AC4: a
TBM face pressure applies only inside its own schedule's chainage band.

No chainage, drive, facility or figure here is real.
"""
from __future__ import annotations

import pathlib
import time

import pytest

from app.blocks.kit_engine import DisabledKit, Figure, load_kit
from app.blocks.kit_engine.invariants import InvariantError, eval_band, parse_invariant

BLOCKS = pathlib.Path(__file__).resolve().parents[2] / "app" / "blocks"
AC4 = "INV-RAIL-5-AC4-CHAINAGE-BAND"


def _band_inv(band=None):
    return parse_invariant(
        {"id": "INV-SYN-QBAND", "kind": "band", "severity": "refuse",
         "applies_to": {"quantity": "syn_q"},
         "band": band or {"min_from": "lo", "max_from": "hi", "subject": "at"},
         "measurement": "synthetic"},
        {}, "synthetic",
    )


def _fig(lo=100, hi=200, at=150, where="asked_about"):
    quals = {}
    if lo is not None:
        quals["lo"] = lo
    if hi is not None:
        quals["hi"] = hi
    asked = {}
    if at is not None:
        (asked if where == "asked_about" else quals)["at"] = at
    return Figure(quantity="syn_q", value=2.2, unit="bar", origin="document",
                  source_id="syn-1", qualifiers=quals, asked_about=asked)


def _verdict(fig, inv=None):
    found = eval_band(inv or _band_inv(), fig, None)
    if found is None:
        return "pass"
    assert found.invariant_id == "INV-SYN-QBAND" and found.severity == "refuse"
    return "refused:" + ",".join(found.missing)


# --------------------------------------------------------- engine band mode --

@pytest.mark.parametrize("lo, hi, at, expect", [
    (100, 200, 150, "pass"),
    (100, 200, 100, "pass"),            # inclusive low end
    (100, 200, 200, "pass"),            # inclusive high end
    (100, 200, 99.9, "refused:at"),
    (100, 200, 200.1, "refused:at"),
    (100, 200, 50, "refused:at"),
    (100, 200, 250, "refused:at"),
    (300, 400, 150, "refused:at"),      # same subject, another figure's band
    (300, 400, 350, "pass"),
    ("100", "200", "150", "pass"),      # numeric strings are numbers
], ids=lambda v: str(v))
def test_the_band_comes_from_the_figures_own_qualifiers(lo, hi, at, expect):
    assert _verdict(_fig(lo, hi, at)) == expect


@pytest.mark.parametrize("drop, missing", [
    ("lo", "lo"), ("hi", "hi"), ("at", "at"),
])
def test_a_missing_qualifier_is_refused_naming_it_not_passed(drop, missing):
    kwargs = {"lo": 100, "hi": 200, "at": 150, drop: None}
    assert _verdict(_fig(**kwargs)) == f"refused:{missing}"


@pytest.mark.parametrize("bad", ["abc", True], ids=["text", "bool"])
def test_a_non_numeric_bound_is_refused_not_passed(bad):
    assert _verdict(_fig(lo=bad)) == "refused:lo"


def test_an_inverted_band_is_refused_naming_both_bounds():
    assert _verdict(_fig(lo=200, hi=100, at=150)) == "refused:lo,hi"


def test_the_subject_falls_back_to_the_figures_qualifiers():
    assert _verdict(_fig(at=150, where="qualifiers")) == "pass"
    assert _verdict(_fig(at=250, where="qualifiers")) == "refused:at"


def test_the_asked_subject_wins_over_a_qualifier_of_the_same_name():
    fig = _fig(at=250)
    fig.qualifiers["at"] = 150
    assert _verdict(fig) == "refused:at"


def test_the_band_reads_the_fields_the_record_names():
    inv = _band_inv({"min_from": "start", "max_from": "end", "subject": "here"})
    ok = Figure(quantity="syn_q", qualifiers={"start": 1, "end": 2}, asked_about={"here": 1.5})
    out = Figure(quantity="syn_q", qualifiers={"start": 1, "end": 2}, asked_about={"here": 3})
    assert eval_band(inv, ok, None) is None
    found = eval_band(inv, out, None)
    assert found is not None and found.missing == ["here"]


@pytest.mark.parametrize("band", [
    {"min_from": "lo", "max_from": "hi"},
    {"min_from": "lo", "subject": "at"},
    {"max_from": "hi", "subject": "at"},
    {"min_from": "", "max_from": "hi", "subject": "at"},
    {"min_from": 1, "max_from": "hi", "subject": "at"},
    {"min_from": "lo", "max_from": "hi", "subject": "at", "min": 0},
    {"min_from": "lo", "max_from": "hi", "subject": "at", "max": 9},
], ids=["no-subject", "no-max", "no-min", "empty", "non-string", "mixed-min", "mixed-max"])
def test_an_incomplete_or_mixed_qualifier_band_does_not_load(band):
    try:
        _band_inv(band)
    except InvariantError as exc:
        refused = str(exc)
    else:
        refused = ""
    assert "INV-SYN-QBAND" in refused, f"{band} loaded as a usable band"


@pytest.mark.parametrize("band", [
    {"min_from": "lo", "max": 9},
    {"max_from": "hi", "min": 0},
    {"subject": "at", "max": 9},
    {"subject": "at", "min": 0},
], ids=["min_from+max", "max_from+min", "subject+max", "subject+min"])
def test_a_partial_qualifier_band_beside_a_fixed_bound_does_not_load(band):
    # Any one qualifier-band key makes it a qualifier band; it must not load as a
    # fixed band and silently drop the qualifier field it names.
    try:
        _band_inv(band)
    except InvariantError as exc:
        refused = str(exc)
    else:
        refused = ""
    assert "INV-SYN-QBAND" in refused, f"{band} loaded as a fixed band"


@pytest.mark.parametrize("point", [100, 0, -5.5])
def test_a_one_point_band_passes_at_its_point_and_refuses_beside_it(point):
    assert _verdict(_fig(lo=point, hi=point, at=point)) == "pass"
    assert _verdict(_fig(lo=point, hi=point, at=point + 1)) == "refused:at"


def test_a_fixed_band_still_works_beside_the_qualifier_mode():
    inv = parse_invariant({"id": "INV-SYN-FIXED", "kind": "band", "severity": "flag",
                           "band": {"min": 0, "max": 10}}, {}, "synthetic")
    assert eval_band(inv, Figure(quantity="syn_q", value=5), None) is None
    assert eval_band(inv, Figure(quantity="syn_q", value=11), None) is not None


# ----------------------------------------------------------------- rail AC4 --

def _rail():
    kit = load_kit(BLOCKS / "rail")
    assert not isinstance(kit, DisabledKit), getattr(kit, "reason", "")
    return kit


def _face_pressure(asked_m, band=(1000, 1400)):
    quals = {"ground_basis": "syn-ground-basis"}
    if band is not None:
        quals.update(chainage_min_m=band[0], chainage_max_m=band[1])
    return Figure(quantity="face_pressure", value=2.2, unit="bar", origin="document",
                  source_id="syn-schedule-1", qualifiers=quals,
                  asked_about={"chainage_m": asked_m})


def _ac4(outcome):
    return [f for f in outcome.findings if f.invariant_id == AC4]


def test_rail_declares_ac4_as_a_refusing_qualifier_band():
    inv = next(i for i in _rail().invariants if i.id == AC4)
    assert inv.kind == "band" and inv.severity == "refuse"
    assert inv.band == {"min_from": "chainage_min_m", "max_from": "chainage_max_m",
                        "subject": "chainage_m"}


@pytest.mark.parametrize("asked_m, refused", [
    (1200, False), (1000, False), (1400, False), (1500, True), (900, True),
])
def test_rail_ac4_face_pressure_outside_its_own_schedule_band_is_refused(asked_m, refused):
    out = _ac4(_rail().tool_time([_face_pressure(asked_m)]))
    if refused:
        assert len(out) == 1 and out[0].severity == "refuse"
        assert out[0].missing == ["chainage_m"]
    else:
        assert out == []


def test_rail_ac4_the_same_chainage_differs_by_schedule():
    kit = _rail()
    assert _ac4(kit.tool_time([_face_pressure(1500, band=(1000, 1400))]))
    assert not _ac4(kit.tool_time([_face_pressure(1500, band=(1400, 1800))]))


def test_rail_ac4_a_schedule_without_its_band_is_refused():
    out = _ac4(_rail().tool_time([_face_pressure(1200, band=None)]))
    assert len(out) == 1 and out[0].missing == ["chainage_min_m", "chainage_max_m"]


# ----------------------------------------------- rail's four derivation guards --
# These run on #21's declaration (manifest derivation_patterns +
# INV-RAIL-DERIVATION-GUARD), on main since #21. They must run; a missing manifest entry fails them.

GUARDS = [
    ("sft_from_installation_temperature",
     "the SFT is inferred from the installation temperature",
     "the SFT is 27 degC per the stressing record"),
    ("scale_clearance_off_drawing",
     "the clearance was scaled off the drawing",
     "the clearance is from the gauging assessment"),
    ("carry_face_pressure_from_similar_drive",
     "use the same face pressure as the similar drive",
     "the face pressure is from this drive's schedule"),
    ("twist_without_base_length",
     "the twist is 5 mm without a base length",
     "the twist is 5 mm over a 3 m base length"),
]


def _guard():
    kit = _rail()
    assert getattr(kit.manifest, "derivation_patterns", None), (
        "rail manifest has no derivation_patterns; the guard tests must run, not skip")
    return kit, next(i for i in kit.invariants if i.id == "INV-RAIL-DERIVATION-GUARD")


@pytest.mark.parametrize("name, dirty, clean", GUARDS, ids=[g[0] for g in GUARDS])
def test_rail_derivation_guard_refuses_its_inference_and_passes_the_clean_companion(
    name, dirty, clean,
):
    kit, inv = _guard()
    base = dict(quantity="sft", origin="document", source_id="syn-doc-1")
    bad = kit._one(inv, Figure(**base, text=dirty), [], {}, (), None)
    assert bad is not None and bad.missing == [name]
    assert kit._one(inv, Figure(**base, text=clean), [], {}, (), None) is None
    shouted = kit._one(inv, Figure(**base, text=dirty.upper()), [], {}, (), None)
    assert shouted is not None and shouted.missing == [name]


# -------------------------- datacentre chiller incident vs INV-DC-CURRENCY-* --

def _dc():
    kit = load_kit(BLOCKS / "datacentre")
    assert not isinstance(kit, DisabledKit), getattr(kit, "reason", "")
    return kit


def _currency(kit, inv_id):
    return next(i for i in kit.invariants if i.id == inv_id)


def test_datacentre_currency_records_are_the_three_the_incident_needs():
    ids = sorted(i.id for i in _dc().invariants if i.id.startswith("INV-DC-CURRENCY-"))
    assert ids == ["INV-DC-CURRENCY-BMS", "INV-DC-CURRENCY-MANUAL-LOG",
                   "INV-DC-CURRENCY-TESTED"]


@pytest.mark.parametrize("event, stale", [
    ("control_sequence_modified", True), ("tested_system_modified", True),
    ("ist_superseded", True), (None, False),
])
def test_chiller_incident_ist_is_stale_after_the_control_change(event, stale):
    kit, now = _dc(), time.time()
    inv = _currency(kit, "INV-DC-CURRENCY-TESTED")
    state = {"ist_register": {"as_of": now}}
    ist = Figure(quantity="tested_result", origin="document", source_id="syn-ist-1")
    events = (event,) if event else ()
    found = kit._one(inv, ist, [ist], state, events, now)
    if stale:
        assert found is not None and found.missing == [event]
    else:
        assert found is None


@pytest.mark.parametrize("inv_id, provider", [
    ("INV-DC-CURRENCY-BMS", "bms"), ("INV-DC-CURRENCY-MANUAL-LOG", "manual_log"),
])
def test_chiller_incident_ride_through_claim_needs_each_live_source(inv_id, provider):
    kit, now = _dc(), time.time()
    inv = _currency(kit, inv_id)
    claim = Figure(quantity="resilience_level", origin="document", source_id="syn-design")
    fresh = {"bms": {"as_of": now}, "manual_log": {"as_of": now}}
    assert kit._one(inv, claim, [claim], fresh, (), now) is None
    down = {k: v for k, v in fresh.items() if k != provider}
    found = kit._one(inv, claim, [claim], down, (), now)
    assert found is not None and found.missing == [provider] and "UNKNOWN" in found.message
    old = dict(fresh, **{provider: {"as_of": now - 7200}})
    found = kit._one(inv, claim, [claim], old, (), now)
    assert found is not None and found.missing == [provider]
