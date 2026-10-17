"""The shared reasoning-layer evaluator: the properties every kit depends on.

Written against the portable spec. The tests that matter most are not the eight
kinds — they are the four properties that decide whether the layer can be
trusted at all:

  * a kit that does not parse REFUSES; it does not load with no invariants
  * an invariant that could never fire is a load failure, not a silent no-op
  * the budget cap SKIPS AND SAYS SO; a skipped check is not a pass
  * the operator's own figure is never refused
"""
from __future__ import annotations

import pathlib
import time

import pytest
import yaml

from app.blocks.kit_engine import (
    DisabledKit,
    Figure,
    KitLoadError,
    KitRegistry,
    check_arithmetic,
    kill_switch_off,
    load_kit,
)

DATACENTRE = pathlib.Path("app/blocks/datacentre")


@pytest.fixture
def kit():
    return load_kit(DATACENTRE)


def _grounded(**kw) -> Figure:
    """A figure with nothing wrong with it, for tests about one thing."""
    base = dict(
        quantity="it_load_mw",
        value=0.7,
        unit="MW",
        origin="document",
        source_id="doc-1",
        source_class="live_measurement",
        qualifiers={"facility": "facility_01"},
        text="the IT load is 0.7 MW",
    )
    base.update(kw)
    return Figure(**base)


def _fresh_state():
    now = time.time()
    # All THREE providers the kit declares. A fixture that supplies two of three
    # makes every currency test look like an UNKNOWN-state test.
    return {
        "bms": {"as_of": now},
        "manual_log": {"as_of": now},
        "ist_register": {"as_of": now},
    }


# ── fail closed ────────────────────────────────────────────────────────────

def test_a_kit_that_does_not_parse_is_disabled_and_refuses(tmp_path):
    """The whole safety property. A typo must not become "no invariants"."""
    (tmp_path / "manifest.yaml").write_text("kit: broken\nquantities: {}\n", encoding="utf-8")
    (tmp_path / "invariants.yaml").write_text("invariants: []\n", encoding="utf-8")

    registry = KitRegistry(tmp_path.parent)
    loaded = registry.load_one(tmp_path)

    assert isinstance(loaded, DisabledKit)
    outcome = loaded.answer_time([_grounded()])
    assert outcome.verdict == "refused"
    assert "DISABLED" in outcome.blocked_reason
    assert "does not pass statements through" in outcome.blocked_reason


def test_an_unknown_kit_refuses_rather_than_returning_none():
    """Absent is refusal too — a None here becomes an ungated answer path."""
    stand_in = KitRegistry(DATACENTRE.parent).get("no_such_kit")
    assert stand_in.answer_time([_grounded()]).verdict == "refused"


def test_a_kit_with_no_invariants_does_not_load(tmp_path):
    (tmp_path / "manifest.yaml").write_text(
        yaml.safe_dump({"kit": "empty", "quantities": {"x": {}}}), encoding="utf-8"
    )
    (tmp_path / "invariants.yaml").write_text("invariants: []\n", encoding="utf-8")

    with pytest.raises(KitLoadError, match="no invariants"):
        load_kit(tmp_path)


def test_the_kill_switch_disables_one_kit_without_a_deploy(tmp_path):
    assert kill_switch_off("datacentre", {"CEREBRUM_KIT_DATACENTRE": "off"}) is True
    assert kill_switch_off("datacentre", {}) is False

    with pytest.raises(KitLoadError, match="switched off"):
        load_kit(DATACENTRE, env={"CEREBRUM_KIT_DATACENTRE": "off"})


# ── an invariant that cannot fire is a load failure ───────────────────────

def _kit_with(tmp_path, record, quantities=None):
    (tmp_path / "manifest.yaml").write_text(
        yaml.safe_dump({
            "kit": "probe",
            "quantities": quantities or {"thing": {"classes": ["any_thing"]}},
        }),
        encoding="utf-8",
    )
    (tmp_path / "invariants.yaml").write_text(
        yaml.safe_dump({"invariants": [record]}), encoding="utf-8"
    )
    return tmp_path


@pytest.mark.parametrize(
    "record,expected",
    [
        ({"id": "A", "kind": "qualifier", "severity": "refuse", "measurement": "m",
          "applies_to": {"quantity": "thing"}}, "requiring no fields"),
        ({"id": "B", "kind": "provenance", "severity": "refuse", "measurement": "m",
          "applies_to": {"quantity": "thing"}}, "must name the dimensions"),
        ({"id": "C", "kind": "band", "severity": "refuse", "measurement": "m",
          "applies_to": {"quantity": "thing"}}, "no band min or max"),
        ({"id": "D", "kind": "authority", "severity": "refuse", "measurement": "m",
          "applies_to": {"quantity": "thing"}}, "governing source class"),
        ({"id": "E", "kind": "currency", "severity": "refuse", "measurement": "m",
          "applies_to": {"quantity": "thing"}}, "state provider"),
        ({"id": "G", "kind": "qualifier", "severity": "refuse", "requires": ["x"],
          "measurement": "m", "applies_to": {"quantity": "not_declared"}},
         "manifest does not declare"),
        ({"id": "H", "kind": "qualifier", "severity": "refuse", "requires": ["x"],
          "measurement": "m", "applies_to": {"quantity": "any_undefined"}},
         "decoration"),
    ],
    ids=["no-requires", "no-across", "no-band", "no-governing", "no-provider",
         "undeclared-quantity", "undefined-class"],
)
def test_a_record_that_could_never_fire_refuses_to_load(tmp_path, record, expected):
    with pytest.raises(KitLoadError, match=expected):
        load_kit(_kit_with(tmp_path, record))


def test_any_star_is_a_class_not_a_wildcard(kit):
    """The bug this caught: units-and-datum demanded a vertical datum for a PCN.

    `any_measured` must govern the measured quantities and NOT the claim-shaped
    ones, or one loose invariant governs everything.
    """
    units = next(inv for inv in kit.invariants if inv.id == "INV-DC-UNITS")
    assert units.governs(Figure(quantity="pue")) is True
    assert units.governs(Figure(quantity="resilience_level")) is False


# ── the budget ────────────────────────────────────────────────────────────

def test_the_budget_skips_and_says_so_rather_than_running_unbounded(kit):
    """An unbounded set in this position consumed 2 GB and killed a live
    instance twice in one day. A skipped check is NOT a pass."""
    kit.budget = 3
    figures = [_grounded() for _ in range(50)]

    outcome = kit.answer_time(figures, state=_fresh_state())

    assert outcome.incomplete is True
    assert outcome.skipped > 0
    assert outcome.as_dict()["incomplete"] is True


def test_within_budget_nothing_is_marked_incomplete(kit):
    outcome = kit.answer_time([_grounded()], state=_fresh_state())
    assert outcome.incomplete is False and outcome.skipped == 0


# ── never refuse the operator's own figure ────────────────────────────────

def test_the_operators_own_figure_is_flagged_never_refused(kit):
    """If they typed the rate it is authoritative input, not a claim to check."""
    theirs = _grounded(origin="operator", source_id=None, source_class=None,
                       quantity="available_capacity", value=300, unit="kW",
                       text="available capacity is 300 kW")

    outcome = kit.answer_time([theirs], state=_fresh_state())

    assert outcome.verdict == "flagged"
    assert outcome.blocked_reason == ""
    assert any(f.softened_from == "refuse" for f in outcome.findings)
    assert any("operator's own figure" in f.message for f in outcome.findings)


def test_the_same_defect_in_a_model_figure_is_refused(kit):
    """The softening is about WHOSE figure it is, not about the defect."""
    mine = _grounded(origin="model", source_id=None, source_class=None,
                     quantity="available_capacity", value=300, unit="kW",
                     text="available capacity is 300 kW")

    assert kit.answer_time([mine], state=_fresh_state()).verdict == "refused"


# ── the five hooks ────────────────────────────────────────────────────────

def test_h0_refuses_before_retrieval(kit):
    outcome = kit.pre_retrieval("is the facility ready for IT load?")
    assert outcome.verdict == "refused"
    assert outcome.hook == "H0"
    assert "nothing was retrieved" in outcome.blocked_reason
    assert "authorised person" in outcome.blocked_reason


def test_h0_lets_an_answerable_question_through_to_retrieval(kit):
    assert kit.pre_retrieval("what is the design PUE?").verdict == "pass"


def test_h1_demotes_a_class_that_is_rejected_as_proof(kit):
    """The tier trap, as a ladder rather than a bespoke branch."""
    tier = _grounded(quantity="resilience_level", value="N+1", unit=None,
                     source_class="tier_design_certificate",
                     qualifiers={"facility": "facility_01", "basis": "as_built"},
                     text="the facility is N+1")

    outcome = kit.ranking([tier])

    assert outcome.verdict == "refused"
    assert outcome.hook == "H1"
    assert "test or a live measurement" in outcome.blocked_reason


def test_h2_catches_an_impossible_value_where_it_is_born(kit):
    outcome = kit.tool_time([_grounded(quantity="pue", value=0.4, unit=None,
                                       text="PUE 0.4", origin="tool")])
    assert outcome.verdict == "refused"
    assert outcome.hook == "H2"
    assert "thermodynamically impossible" in outcome.blocked_reason


def test_h4_reruns_the_answer_time_checks_on_the_deliverable(kit):
    """H3 alone lets a corrupted value reach exports and source panels."""
    bad = _grounded(quantity="resilience_level", value="N+1", unit=None,
                    source_class="live_measurement",
                    qualifiers={"facility": "facility_01"},
                    text="the facility is N+1")

    at_answer = kit.answer_time([bad], state=_fresh_state())
    at_export = kit.export_time([bad], state=_fresh_state())

    assert at_answer.verdict == at_export.verdict == "refused"
    assert at_export.hook == "H4"
    assert {f.invariant_id for f in at_answer.findings} == {f.invariant_id for f in at_export.findings}


# ── the kinds whose absence was the reason for the rewrite ───────────────

def test_currency_reports_unknown_and_never_falls_back_to_the_design_basis(kit):
    claim = _grounded(quantity="resilience_level", value="N+1", unit=None,
                      source_class="live_measurement",
                      qualifiers={"facility": "facility_01", "basis": "as_currently_operating"},
                      text="the facility is N+1")

    outcome = kit.answer_time([claim], state={})

    assert outcome.verdict == "refused"
    assert "UNKNOWN" in outcome.blocked_reason
    assert "no design-basis fallback" in outcome.blocked_reason
    assert "N+1" not in outcome.blocked_reason


def test_currency_is_an_event_not_only_a_clock(kit):
    """An IST result is stale the moment the tested systems change, however
    recent the test was — the live chiller incident."""
    claim = _grounded(quantity="tested_result", value=None, unit=None,
                      source_class="integrated_systems_test",
                      qualifiers={"facility": "facility_01", "commissioning_level": "L5",
                                  "load_pct": 100, "failure_scenario": "chiller loss"},
                      text="tested at L5, 100% load, chiller loss")

    fresh = kit.answer_time([claim], state=_fresh_state())
    after = kit.answer_time([claim], state=_fresh_state(),
                            events=["control_sequence_modified"])

    assert fresh.verdict == "pass", fresh.blocked_reason
    assert after.verdict == "refused"
    assert "control_sequence_modified" in after.blocked_reason


def test_provenance_does_not_fire_when_one_entity_is_named_twice(kit):
    """The bug written and fixed by hand in the first kit: a mention-counting
    guard blocks what a CORRECT answer looks like."""
    ok = _grounded(quantity="available_capacity", value=300, unit="kW",
                   qualifiers={"facility": "facility_01",
                               "redundancy_basis": "available_after_redundancy"},
                   text="facility_01 has 300 kW available after redundancy in facility_01")
    ok.asked_about = {"facility": "facility_01"}

    assert kit.answer_time([ok], state=_fresh_state()).verdict == "pass"


def test_provenance_fires_when_the_figure_belongs_to_another_entity(kit):
    borrowed = _grounded(quantity="available_capacity", value=300, unit="kW",
                         qualifiers={"facility": "facility_02",
                                     "redundancy_basis": "available_after_redundancy"},
                         text="300 kW available after redundancy")
    borrowed.asked_about = {"facility": "facility_01"}

    outcome = kit.answer_time([borrowed], state=_fresh_state())

    assert outcome.verdict == "refused"
    assert "facility_02" in outcome.blocked_reason and "facility_01" in outcome.blocked_reason


@pytest.mark.parametrize(
    "text,expected",
    [
        ("L/20 = 4800/20 = 200 mm", True),
        ("L/20 = 4800/20 = 240 mm", False),
        ("total is 12 * 4 = 48 units", False),
        ("total is 12 * 4 = 50 units", True),
        ("no arithmetic here at all", False),
    ],
)
def test_derivation_evaluates_the_arithmetic_a_reader_would_skim(text, expected):
    """Rule right, inputs right, result wrong — the hardest defect to see by
    reading and trivial to catch by evaluating."""
    assert (check_arithmetic(text) is not None) is expected


def test_derivation_catches_an_answer_contradicting_itself(kit):
    """Live: "40 days" and "400 days" in one answer."""
    first = _grounded(quantity="ups_autonomy_minutes", value=30, unit="minutes",
                      text="UPS autonomy is 30 minutes")
    second = _grounded(quantity="ups_autonomy_minutes", value=300, unit="minutes",
                       text="UPS autonomy is 300 minutes")

    outcome = kit.answer_time([first, second], state=_fresh_state())

    assert outcome.verdict == "refused"
    assert "contradicts itself" in outcome.blocked_reason


def test_grounding_refuses_a_figure_nobody_supplied(kit):
    invented = _grounded(origin="model", source_id=None, source_class=None)

    outcome = kit.answer_time([invented], state=_fresh_state())

    assert outcome.verdict == "refused"
    assert "not grounded" in outcome.blocked_reason


def test_a_qualifier_the_kit_does_not_declare_is_refused_before_any_invariant(kit):
    """An invariant reading a field it cannot trust is worse than no invariant."""
    outcome = kit.answer_time(
        [_grounded(qualifiers={"facility": "facility_01", "made_up_field": "x"})],
        state=_fresh_state(),
    )

    assert outcome.verdict == "refused"
    assert any(f.invariant_id == "SCHEMA" for f in outcome.findings)
    assert "not a declared qualifier field" in outcome.blocked_reason


def test_a_finding_carries_the_span_so_one_figure_can_be_repaired(kit):
    """Surgical repair: a long answer with one bad number need not be binned."""
    figure = _grounded(quantity="pue", value=0.4, unit=None, origin="tool",
                       text="PUE 0.4", span={"start": 412, "end": 419})

    finding = kit.tool_time([figure]).findings[0]

    assert finding.span == {"start": 412, "end": 419}


# ── every invariant declares how it will be counted ──────────────────────

def test_every_shipped_invariant_names_its_measurement_case(kit):
    """An invariant you cannot count is an opinion."""
    for inv in kit.invariants:
        assert inv.measurement, f"{inv.id} ships without a measurement case"
        assert any(ch.isdigit() for ch in inv.measurement), (
            f"{inv.id}'s measurement names no number of runs: {inv.measurement}"
        )


def test_a_record_with_no_measurement_loads_but_does_not_ship(tmp_path):
    """Spec §4 says no invariant SHIPS without a measurement case -- the word is
    *ships*, and §5 puts the AC tests in the kit's own tests/. So the kit LOADS
    and gates; the ship gate (certification, signing) is what refuses."""
    (tmp_path / "manifest.yaml").write_text(
        yaml.safe_dump({
            "kit": "unmeasured_probe",
            "quantities": {"thing": {}},
            "qualifier_fields": {"who": {"type": "string"}},
        }),
        encoding="utf-8",
    )
    (tmp_path / "invariants.yaml").write_text(
        yaml.safe_dump({"invariants": [{
            "id": "INV-PROBE", "kind": "qualifier", "severity": "refuse",
            "applies_to": {"quantity": "thing"}, "requires": ["who"],
        }]}),
        encoding="utf-8",
    )

    probe = load_kit(tmp_path)

    assert probe.invariants, "the kit must still gate"
    assert probe.unmeasured == ["INV-PROBE"]
    assert probe.ships is False


def test_a_kit_whose_records_all_declare_a_measurement_ships(kit):
    assert kit.unmeasured == []
    assert kit.ships is True


def test_a_presence_band_may_run_at_answer_time_a_numeric_band_may_not():
    """Two rules wear the name `band`. A POSSIBILITY band must be caught where
    the value is born (H2). A TWO-SIDEDNESS band is about the ANSWER being
    single-sided, which cannot be seen at tool time -- there is one figure and no
    answer yet."""
    from app.blocks.kit_engine.invariants import legal_hooks

    assert "H3" in legal_hooks("band", {"min": "present", "max": "present"})
    assert "H3" not in legal_hooks("band", {"min": 1.0, "max": 3.5})


def test_the_rewritten_datacentre_kit_covers_all_eight_kinds(kit):
    """The reason for the rewrite: four of the eight kinds were absent from the
    hand-written gate — authority, band, derivation and grounding."""
    kinds = {inv.kind for inv in kit.invariants}
    assert kinds >= {
        "qualifier", "scope", "authority", "provenance",
        "currency", "band", "derivation", "grounding", "unit_discipline",
    }


# --------------------------------------------------------------------------
# a check that could not run is not a pass
# --------------------------------------------------------------------------

def test_a_band_it_cannot_evaluate_reports_that_rather_than_passing():
    """The repo's silent-except guard caught this. `try: float(v) except: return
    None` meant a figure carrying a non-numeric value sailed through the one check
    that exists to catch an impossible magnitude -- a skipped check reported as a
    pass, which is the defect the whole layer exists to prevent."""
    from app.blocks.kit_engine.invariants import _as_number

    assert _as_number("not a number") is None
    assert _as_number("1.4") == 1.4, "a numeric string is still a number"
    assert _as_number("1,200") == 1200.0
    assert _as_number(True) is None, "a boolean is never a magnitude"
    assert _as_number(None) is None


def test_a_non_numeric_value_under_a_band_is_refused_by_the_engine(tmp_path):
    import shutil

    from app.blocks.kit_engine import Figure, load_kit

    root = pathlib.Path(__file__).resolve().parents[2] / "app" / "blocks" / "datacentre"
    for name in ("manifest.yaml", "invariants.yaml", "design_basis.yaml"):
        shutil.copy2(root / name, tmp_path / name)
    kit = load_kit(tmp_path)

    outcome = kit.tool_time([Figure(
        quantity="pue", value="one point four", origin="document", source_id="d1",
        text="PUE one point four")])
    messages = " ".join(f.message for f in outcome.findings)
    assert outcome.verdict == "refused", messages
    assert "not a number" in messages and "unchecked band is not a pass" in messages


def test_an_export_time_record_is_actually_evaluated_at_export_time(kit):
    """`at(H4)` mapped H4 to H3 alone, so a record declaring `hook: H4` was selected
    at NO hook: H3 skipped it (its hook is H4) and H4 looked for H3. The Store had
    one -- water_treatment's INV-WT-CURRENCY -- and it had never fired in its life.

    Load-time refuses a record that could never fire, and it was right to pass this
    one: `allowed_hooks` adds H4 wherever H3 is legal, so the DECLARATION was valid.
    The hole was in the router, which cannot be seen by a check that reads the
    record's own fields.
    """
    from app.blocks.kit_engine.invariants import (
        H3_ANSWER_TIME,
        H4_EXPORT_TIME,
        parse_invariant,
    )

    record = parse_invariant({
        "id": "INV-EXPORT-ONLY", "kind": "currency", "severity": "refuse",
        "hook": "H4",
        "applies_to": {"quantity": "pue"},
        "window": {"provider": "bms", "max_age": "event"},
        "message": "pue from a superseded reading",
        "measurement": "20 exports after a bms change. Before: n stale. After: 0.",
    }, kit.manifest.quantity_classes(), where="test")
    kit.invariants.append(record)

    assert record.hooks() == (H4_EXPORT_TIME,)
    assert record in kit.at(H4_EXPORT_TIME), (
        "a record declaring H4 must be evaluated at H4 — otherwise it is a dead rule "
        "that load-time cannot see"
    )
    assert record not in kit.at(H3_ANSWER_TIME), "H4 is later material, not answer time"

    # And the H3 set still re-runs at H4: that is what H4 is for.
    answer_time = kit.at(H3_ANSWER_TIME)
    assert answer_time, "the kit has answer-time records"
    assert all(inv in kit.at(H4_EXPORT_TIME) for inv in answer_time)


def test_every_store_record_is_reachable_at_some_hook():
    """The property the H4 bug violated, asserted across the whole Store rather than
    for one kit: a record the router never asks for is a rule that does not exist."""
    from app.blocks.kit_engine import load_kit as _load

    unreachable = []
    for manifest in sorted(pathlib.Path("app/blocks").glob("*/manifest.yaml")):
        directory = manifest.parent
        if not (directory / "invariants.yaml").is_file():
            continue
        loaded = _load(directory)
        for inv in loaded.invariants:
            # H0 included: a `scope` record runs pre-retrieval, where the dispatch is
            # `eval_scope` against the MANIFEST's patterns rather than a per-record
            # check. It still has to be one the router asks for at H0, which is what
            # this asserts; that its patterns actually refuse is
            # test_every_invariant_bites.py's job.
            if not any(inv in loaded.at(hook) for hook in ("H0", "H1", "H2", "H3", "H4")):
                unreachable.append(f"{directory.name}:{inv.id} ({inv.kind}, "
                                   f"declares {inv.hooks()})")
    assert not unreachable, f"records no hook ever asks for: {unreachable}"


# --------------------------------------------------------------------------
# G1: a key the engine does not read is refused, not discarded
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad_key,value", [
    ("cross_check", ["a", "b"]),
    ("require_qualifiers", ["x"]),
    ("override_class_on_event_day", "pitch_report"),
    ("spec_extension", True),
])
def test_unknown_invariant_key_refuses(tmp_path, bad_key, value):
    """A key the parser discards gates NOTHING while the record loads clean and
    reports green. All four of these were written into a real kit draft."""
    (tmp_path / "manifest.yaml").write_text(
        yaml.safe_dump({"kit": "probe", "quantities": {"q": {"units": ["m"]}}}),
        encoding="utf-8")
    (tmp_path / "invariants.yaml").write_text(yaml.safe_dump({"invariants": [{
        "id": "X", "kind": "qualifier", "severity": "refuse",
        "applies_to": {"quantity": "q"}, "requires": ["f"], "message": "m",
        "measurement": "Probe x20 without the field. Before: n stated. After: 0.",
        bad_key: value,
    }]}), encoding="utf-8")

    with pytest.raises(KitLoadError) as exc:
        load_kit(tmp_path)
    assert bad_key in str(exc.value)
    assert "X" in str(exc.value), "the record must be named, or nobody can find it"


def test_an_unread_applies_to_key_refuses(tmp_path):
    """`applies_to` selects what a record governs. The engine reads `quantity` and
    `claim_class` and nothing else, so anything else there reads as a narrowing and
    is not one. Six Store invariants carried a dead `spec_extension` for weeks."""
    (tmp_path / "manifest.yaml").write_text(
        yaml.safe_dump({"kit": "probe", "quantities": {"q": {"units": ["m"]}}}),
        encoding="utf-8")
    (tmp_path / "invariants.yaml").write_text(yaml.safe_dump({"invariants": [{
        "id": "Y", "kind": "qualifier", "severity": "refuse",
        "applies_to": {"quantity": "q", "spec_extension": True},
        "requires": ["f"], "message": "m",
        "measurement": "Probe x20. Before: n. After: 0.",
    }]}), encoding="utf-8")

    with pytest.raises(KitLoadError) as exc:
        load_kit(tmp_path)
    assert "spec_extension" in str(exc.value) and "Y" in str(exc.value)


def test_the_allowed_key_set_is_the_dataclass_not_a_second_copy():
    """A hand-written allowlist drifts from the parser, and the parser is what
    decides behaviour. Adding a field to Invariant must allow that key with no
    second edit; removing one must stop allowing it."""
    from dataclasses import fields as dataclass_fields

    from app.blocks.kit_engine.invariants import (
        ALLOWED_APPLIES_TO_KEYS,
        Invariant,
        _allowed_invariant_keys,
    )

    allowed = _allowed_invariant_keys()
    declared = {f.name for f in dataclass_fields(Invariant) if not f.name.startswith("_")}
    assert declared <= allowed, f"a real field is refused: {sorted(declared - allowed)}"
    # Exactly one alias, and it is the one the parser accepts.
    assert allowed - declared == {"governing_class"}
    assert ALLOWED_APPLIES_TO_KEYS == frozenset({"quantity", "claim_class"})


def test_every_key_the_store_uses_is_allowed():
    """The guard must not disable the Store it protects. A draft allowlist omitted
    `measurement`, which is on all 217 records."""
    from app.blocks.kit_engine.invariants import (
        ALLOWED_APPLIES_TO_KEYS,
        _allowed_invariant_keys,
    )

    allowed = _allowed_invariant_keys()
    offenders = []
    for path in sorted(pathlib.Path("app/blocks").glob("*/invariants.yaml")):
        for record in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get(
                "invariants") or []:
            for key in set(record) - allowed:
                offenders.append(f"{path.parent.name}/{record.get('id')}:{key}")
            for key in set(record.get("applies_to") or {}) - ALLOWED_APPLIES_TO_KEYS:
                offenders.append(f"{path.parent.name}/{record.get('id')}:applies_to.{key}")
    assert not offenders, offenders


# --- inert live-state gates cannot be declared ------------------------------

def test_requires_state_on_a_kind_that_ignores_it_refuses_to_load():
    """An inert state gate under-refuses in silence, so it must not parse.

    A dead qualifier over-refuses and somebody notices. A dead STATE gate lets the
    figure through with the state UNKNOWN, which is the one outcome the whole
    live-state rule exists to prevent — and it reads, in the declaration, exactly
    like a working gate. stadium_venue declared two of these on `qualifier`
    records: a licensed capacity with the open-stand set unknown, and a rigging
    load with the roof position unknown.
    """
    from app.blocks.kit_engine.invariants import InvariantError, parse_invariant

    with pytest.raises(InvariantError) as exc:
        parse_invariant({
            "id": "X-QUAL-STATE", "kind": "qualifier",
            "applies_to": {"quantity": "q"}, "requires": ["a"],
            "requires_state": ["stands_open"], "block_if_missing_state": True,
            "severity": "refuse", "message": "m",
            "measurement": "irrelevant to this test",
        }, {}, "test")
    assert "requires_state" in str(exc.value)
    assert "qualifier" in str(exc.value)
    assert "stands_open" in str(exc.value), "the refusal must name the unchecked state"


def test_requires_state_without_block_if_missing_state_refuses_to_load():
    """`state_precondition` returns before checking unless it is armed, so an
    unarmed requirement is declared and never enforced."""
    from app.blocks.kit_engine.invariants import InvariantError, parse_invariant

    with pytest.raises(InvariantError) as exc:
        parse_invariant({
            "id": "X-CUR-STATE", "kind": "currency",
            "applies_to": {"quantity": "q"},
            "window": {"provider": "p", "max_age": "event"},
            "requires_state": ["pa_operational"],
            "severity": "refuse", "message": "m",
            "measurement": "irrelevant to this test",
        }, {}, "test")
    assert "block_if_missing_state" in str(exc.value)


def test_an_armed_state_gate_on_a_state_aware_kind_still_loads():
    """The companion. A guard that refused every state gate would pass both tests
    above while disabling the feature."""
    from app.blocks.kit_engine.invariants import parse_invariant

    inv = parse_invariant({
        "id": "X-DERIV-STATE", "kind": "derivation",
        "applies_to": {"quantity": "q"},
        "requires_state": ["roof_state"], "block_if_missing_state": True,
        "severity": "refuse", "message": "m",
        "measurement": "irrelevant to this test",
    }, {}, "test")
    assert inv.requires_state == ("roof_state",)
    assert inv.block_if_missing_state is True


def test_state_aware_kinds_matches_the_evaluators_that_read_state():
    """The constant must stay true of the code, or the guard above starts lying.

    Drift is how the original hole opened: `state_precondition`'s docstring says
    "usable by any kind", and only two evaluators ever called it. A hand-maintained
    list would rot the same way, so this reads the source of every `eval_*`
    function and derives the set.
    """
    import inspect

    from app.blocks.kit_engine import invariants as module

    reads_state = set()
    for name, fn in vars(module).items():
        if not name.startswith("eval_") or not callable(fn):
            continue
        if "state_precondition(" in inspect.getsource(fn):
            reads_state.add(name[len("eval_"):])

    assert reads_state == set(module.STATE_AWARE_KINDS), (
        f"STATE_AWARE_KINDS says {sorted(module.STATE_AWARE_KINDS)} but the "
        f"evaluators that call state_precondition are {sorted(reads_state)}. "
        f"Either an evaluator gained or lost the call, or the constant is stale — "
        f"and a stale constant here means requires_state is silently inert again."
    )
