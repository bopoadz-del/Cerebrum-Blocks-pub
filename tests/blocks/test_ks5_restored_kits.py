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
  * rail's four never-allowed derivations (formerly host-side) refuse, each
    naming itself, and a clean companion passes;
  * the datacentre chiller-incident regression: a pre-correction IST result
    is stale after the control change; the retested sequence is citable.

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


RAIL_GUARD = [
    ("sft_from_installation_temperature",
     "the SFT is inferred from the installation temperature", "the SFT is 27 degC per the stressing record"),
    ("scale_clearance_off_drawing",
     "the clearance was scaled off the drawing", "the clearance is from the gauging assessment"),
    ("carry_face_pressure_from_similar_drive",
     "use the face pressure from a similar drive", "the face pressure is from this drive's schedule"),
    ("twist_without_base_length",
     "the twist is 5 mm without a base length", "the twist is 5 mm over a 3 m base length"),
]


@pytest.mark.parametrize("name, bad, good", RAIL_GUARD, ids=[r[0] for r in RAIL_GUARD])
def test_rail_never_allowed_derivation_is_refused_and_names_itself(name, bad, good):
    kit = _kit("rail")
    records = {i.id: i for i in kit.invariants}
    assert "INV-RAIL-DERIVATION-GUARD" in records, "rail declares no derivation guard"
    inv = records["INV-RAIL-DERIVATION-GUARD"]
    q = next(iter(kit.manifest.quantities))
    hit = kit._one(inv, Figure(quantity=q, text=bad), [], None, (), None)
    assert hit is not None and hit.missing == [name]
    assert kit._one(inv, Figure(quantity=q, text=good), [], None, (), None) is None


def test_rail_derivation_guard_refuses_through_the_answer_hook():
    kit = _kit("rail")
    now = time.time()
    fig = Figure(quantity="sft", value=27, unit="degC", origin="document", source_id="syn",
                 text="the SFT is inferred from the installation temperature")
    out = kit.answer_time([fig], state=_fresh_state(kit, now), now=now)
    assert out.verdict == "refused"
    assert "INV-RAIL-DERIVATION-GUARD" in {f.invariant_id for f in out.findings}


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


# ---- load-time mandatory qualifiers (restored from the deleted *Basis loaders) --
import shutil  # noqa: E402

from app.blocks.kit_engine import InterviewError, load_design_basis  # noqa: E402


def _load(directory):
    """'loaded:<n figures>' or 'refused:<message>' -- comparable, so a wrong
    outcome is an assertion, never an uncaught error."""
    try:
        db = load_design_basis(directory)
    except InterviewError as exc:
        return f"refused:{exc}"
    return f"loaded:{len(db.figures)}"


def _register(tmp_path, required, figure_text):
    d = tmp_path / "kx"
    d.mkdir()
    if required is not None:
        (d / "manifest.yaml").write_text(
            "kit: kx\nmandatory_qualifiers: " + required + "\n", encoding="utf-8")
    (d / "design_basis.yaml").write_text("design_basis:\n" + figure_text, encoding="utf-8")
    return d


FULL = "  f_a:\n    value: null\n    unit: u\n    q1: null\n"
HALF = "  f_a:\n    value: null\n    unit: u\n"


@pytest.mark.parametrize("required, figures, expect", [
    ("[value, unit, q1]", FULL, "loaded:1"),
    ("[value, unit, q1]", HALF, "refused:half-qualified f_a q1"),
    ("[value, unit, q1]", "  f_a: 3\n", "refused:not a mapping f_a"),
    (None, HALF, "loaded:1"),            # no manifest: nothing declared
    ("[]", HALF, "loaded:1"),            # declared empty
    ("[value]", "  f_a: 3\n", "refused:not a mapping f_a"),
    ("{q1: yes}", FULL, "refused:must be a list"),
])
def test_a_half_qualified_figure_is_refused_at_load_time(tmp_path, required, figures, expect):
    got = _load(_register(tmp_path, required, figures))
    if expect.startswith("refused:"):
        words = expect[len("refused:"):].split()
        assert got.startswith("refused:") and all(w in got for w in words), got
    else:
        assert got == expect


def test_a_figure_register_without_a_requirement_loads_a_non_mapping_entry(tmp_path):
    d = tmp_path / "ky"
    d.mkdir()
    (d / "manifest.yaml").write_text("kit: ky\n", encoding="utf-8")
    (d / "design_basis.yaml").write_text("design_basis:\n  f_a: 3\n", encoding="utf-8")
    assert _load(d) == "loaded:1"


QUALIFIED_KITS = ("fire_protection", "offshore_marine", "og_operations", "rail", "water_treatment")


@pytest.mark.parametrize("kit_name", QUALIFIED_KITS)
def test_each_kit_declares_its_qualifiers_and_refuses_a_figure_missing_one(tmp_path, kit_name):
    src = BLOCKS / kit_name
    import yaml
    declared = (yaml.safe_load((src / "manifest.yaml").read_text(encoding="utf-8")) or {}).get(
        "mandatory_qualifiers") or []
    assert "value" in declared and "unit" in declared and len(declared) > 2
    assert _load(src).startswith("loaded:")
    d = tmp_path / kit_name
    shutil.copytree(src, d)
    raw = yaml.safe_load((d / "design_basis.yaml").read_text(encoding="utf-8"))
    block = next(b for b in raw if isinstance(raw[b], dict) and raw[b]
                 and all(isinstance(v, dict) for v in raw[b].values()))
    first = next(iter(raw[block]))
    dropped = declared[-1]
    raw[block][first].pop(dropped, None)
    (d / "design_basis.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    got = _load(d)
    assert got.startswith("refused:") and first in got and dropped in got, got
