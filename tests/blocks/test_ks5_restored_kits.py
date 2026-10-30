"""K-S5 repair: the coverage of the six deleted hand-written gate test files,
rebuilt on the declarative kits that replace those gates.

The deleted files drove ``gate_answer`` / ``*ReasoningBlock`` -- host modules
K-S5 removed. Every acceptance criterion they asserted is now a record in
app/blocks/<kit>/invariants.yaml (or a manifest scope refusal), evaluated by
app.blocks.kit_engine. So the behaviour is still in the tree, and it is tested
here, generically, on synthetic figures:

  * every invariant of every one of the six kits FIRES on a synthetic figure
    built to violate it, naming its own id, and does NOT fire on a synthetic
    figure that satisfies it (two inputs, two results, per record);
  * every scope-refusal question the deleted files asked is refused before
    retrieval, and an ordinary question is not;
  * the datacentre chiller-incident regression: a pre-correction IST result
    is stale after the control change; the retested sequence is citable.

rail's four never-allowed derivations are tested with their declaration in
#21 (test_kit_derivation_patterns.py); the load-time mandatory qualifiers with
theirs in #22 (test_kit_mandatory_qualifiers.py).

No figure value, facility or project here is real -- all synthetic.
"""
from __future__ import annotations

import pathlib
import time

import pytest

from app.blocks.kit_engine import DisabledKit, Figure, load_kit

BLOCKS = pathlib.Path(__file__).resolve().parents[2] / "app" / "blocks"
KITS = ("datacentre", "fire_protection", "offshore_marine", "og_operations",
        "rail", "water_treatment")


def _kit(name):
    return load_kit(BLOCKS / name)


def _quantity(kit, inv):
    """A quantity the record governs, taken from the kit's own manifest."""
    for q in inv.quantities() or ("any",):
        if q == "any":
            return next(iter(kit.manifest.quantities))
        if q.startswith("any_"):
            return kit.manifest.quantity_classes()[q][0]
        return q


def _fresh_state(kit, now):
    return {name: {"as_of": now} for name in kit.manifest.state_providers}


def _pair(kit, inv, now):
    """(violating figure, satisfying figure, state for each) for one record."""
    q = _quantity(kit, inv)
    base = dict(quantity=q, origin="document", source_id="syn-doc-1",
                source_class=(inv.governing[0] if inv.governing else None))
    fresh = _fresh_state(kit, now)
    good_q = {f: "syn" for f in tuple(inv.requires) + tuple(inv.requires_any_of[:1])}
    if inv.require_qualifier:
        good_q[inv.require_qualifier] = "syn"
    k = inv.kind
    if k == "qualifier":
        return Figure(**base), Figure(**base, qualifiers=good_q), fresh, fresh
    if k == "grounding":
        return (Figure(quantity=q, origin="model"), Figure(**base), fresh, fresh)
    if k == "authority":
        bad = dict(base, source_class=None)
        return Figure(**bad, qualifiers=good_q), Figure(**base, qualifiers=good_q), fresh, fresh
    if k == "provenance":
        if inv.forbid:
            return (Figure(**base, derivations=[inv.forbid[0]]), Figure(**base), fresh, fresh)
        d = inv.across[0]
        return (Figure(**base, qualifiers={d: "syn_a"}, asked_about={d: "syn_b"}),
                Figure(**base, qualifiers={d: "syn_a"}, asked_about={d: "syn_a"}), fresh, fresh)
    if k == "currency":
        return Figure(**base), Figure(**base), {}, fresh
    if k == "band":
        low, high = inv.band.get("min"), inv.band.get("max")
        if str(low) == "present" or str(high) == "present":
            ok = {"min": 1, "max": 2, "source_id_min": "s", "source_id_max": "s"}
            return Figure(**base, value=1), Figure(**base, value=1, bounds=ok), fresh, fresh
        inside = low if low is not None else high
        outside = (high + abs(high) + 1) if high is not None else (low - abs(low) - 1)
        return Figure(**base, value=outside), Figure(**base, value=inside), fresh, fresh
    if k == "unit_discipline":
        units = kit.manifest.quantities[q].units
        good = dict(base, unit=(units[0] if units else None),
                    text=" ".join(inv.requires_one_of[:1]) + " syn")
        if inv.requires:
            return Figure(**good), Figure(**good, qualifiers=good_q), fresh, fresh
        if inv.requires_one_of:
            return (Figure(**dict(good, text="syn", unit=None)), Figure(**good), fresh, fresh)
        return Figure(**dict(base, text="the figure is 5")), Figure(**good), fresh, fresh
    if k == "derivation":
        good = dict(base, steps=list(inv.requires_steps), qualifiers=good_q)
        if inv.block_if:
            return Figure(**good, conditions=[inv.block_if[0]]), Figure(**good), fresh, fresh
        if inv.forbid:
            return Figure(**good, derivations=[inv.forbid[0]]), Figure(**good), fresh, fresh
        return Figure(**dict(good, text="2 x 3 = 7")), Figure(**dict(good, text="2 x 3 = 6")), fresh, fresh
    raise AssertionError(f"no synthetic builder for kind {k}")


RECORDS = [
    (k, inv.id) for k in KITS for inv in _kit(k).invariants if inv.kind != "scope"
]


def test_all_six_kits_load_rather_than_disabling_themselves():
    for k in KITS:
        kit = _kit(k)
        assert not isinstance(kit, DisabledKit), k
        assert kit.invariants, k


def test_every_shipped_invariant_names_its_measurement_case():
    for k in KITS:
        for inv in _kit(k).invariants:
            assert inv.measurement.strip(), f"{k}:{inv.id} has no measurement case"


@pytest.mark.parametrize("kit_name, inv_id", RECORDS, ids=[f"{k}:{i}" for k, i in RECORDS])
def test_every_invariant_fires_on_its_violation_and_not_on_a_satisfying_figure(kit_name, inv_id):
    kit = _kit(kit_name)
    inv = next(i for i in kit.invariants if i.id == inv_id)
    now = time.time()
    bad, good, bad_state, good_state = _pair(kit, inv, now)
    fired = kit._one(inv, bad, [bad], bad_state, (), now)
    assert fired is not None and fired.invariant_id == inv_id
    assert kit._one(inv, good, [good], good_state, (), now) is None


SCOPE_QUESTIONS = {
    "datacentre": ["is the facility ready for IT load?"],
    "fire_protection": ["what hazard class is this?", "is this building adequately protected?",
                        "can we close this valve?", "is a fire watch enough?",
                        "can we occupy before testing?", "will this pass?",
                        "is this fire stopping OK?"],
    "offshore_marine": ["can we start the lift?", "can we start the pull-in?",
                        "can we commence the lay?", "is the weather OK?",
                        "can we run on two thrusters?", "is it safe to dive?",
                        "can we get closer?"],
    "og_operations": ["can we keep running with this?", "is it safe to break containment here?",
                      "can we bypass this trip?", "can we extend this inspection?",
                      "is this vessel fit for service?"],
    "rail": ["is it safe to work with adjacent line open?", "can we hand the line back tonight?",
             "can we put the crane here?", "can we stress the rail today?",
             "is this building at risk?", "can we go into the four-foot?"],
    "water_treatment": ["is this water safe to supply?", "can we skip filter-to-waste?",
                        "do we need a boil notice?", "can I enter the chlorine room?"],
}
SCOPE_CASES = [(k, q) for k, qs in SCOPE_QUESTIONS.items() for q in qs]


@pytest.mark.parametrize("kit_name, question", SCOPE_CASES)
def test_every_scope_question_is_refused_before_retrieval_naming_its_authority(kit_name, question):
    outcome = _kit(kit_name).pre_retrieval(question)
    assert outcome.verdict == "refused"
    assert outcome.findings and outcome.findings[0].kind == "scope"


@pytest.mark.parametrize("kit_name", KITS)
def test_an_ordinary_question_is_not_scope_refused(kit_name):
    assert _kit(kit_name).pre_retrieval("what unit is this figure quoted in?").verdict == "pass"


def test_datacentre_chiller_incident_pump_sequence_regression():
    # Synthetic replay of the encoding sheet's incident: a chiller-failure IST
    # result, then the control sequence is modified and retested.
    kit = _kit("datacentre")
    now = time.time()
    state = _fresh_state(kit, now)
    ist = Figure(quantity="tested_result", origin="document", source_id="syn-ist",
                 source_class="ist_record" if "ist_record" in kit.manifest.source_classes else None,
                 text="the IST result from before the control change still applies")
    inv = next(i for i in kit.invariants if i.id == "INV-DC-CURRENCY-TESTED")
    stale = kit._one(inv, ist, [ist], state, ("control_sequence_modified",), now)
    assert stale is not None and "stale" in stale.message
    retested = Figure(quantity="tested_result", origin="document", source_id="syn-ist-retest",
                      text="per the retested control sequence, rise is within limits")
    assert kit._one(inv, retested, [retested], state, (), now) is None
