"""kit_engine manifest ``derivation_patterns`` and rail's derivation guard.

A kit names never-allowed inferences it can see in statement text as
name -> regex in manifest.yaml; a provenance record's ``forbid`` list refuses
them through the shared evaluator. rail declares its four (formerly host-side
pattern checks in reasoning.py) as INV-RAIL-DERIVATION-GUARD.

Every malformed declaration is a load-time ManifestError, never a silent
no-op. All figures and text are synthetic.
"""
from __future__ import annotations

import copy
import pathlib
import time

import pytest
import yaml

from app.blocks.kit_engine import Figure, load_kit
from app.blocks.kit_engine import invariants as _inv
from app.blocks.kit_engine.manifest import ManifestError, parse_manifest

BLOCKS = pathlib.Path(__file__).resolve().parents[2] / "app" / "blocks"
RAIL_RAW = yaml.safe_load((BLOCKS / "rail" / "manifest.yaml").read_text(encoding="utf-8"))


def _parse(patterns):
    """'ok:<sorted names>' or 'refused:<message>' -- comparable, so a wrong
    outcome is an assertion, never an uncaught error."""
    raw = copy.deepcopy(RAIL_RAW)
    raw["derivation_patterns"] = patterns
    try:
        m = parse_manifest(raw, where="syn")
    except ManifestError as exc:
        return f"refused:{exc}"
    except Exception as exc:  # an unrelated error is a wrong outcome, not a crash
        return f"crashed:{type(exc).__name__}"
    names = getattr(m, "derivation_patterns", None)
    if names is None:
        return "nofield"
    return "ok:" + ",".join(sorted(names))


def test_a_valid_mapping_loads_and_an_absent_one_is_empty():
    assert _parse({"syn_a": "foo", "syn_b": "bar"}) == "ok:syn_a,syn_b"
    assert _parse(None) == "ok:"


@pytest.mark.parametrize("bad", [["syn_a"], "foo", 3])
def test_derivation_patterns_of_the_wrong_type_is_refused(bad):        # H1
    got = _parse(bad)
    assert got.startswith("refused:") and "must map a name to a regex" in got, got


def test_an_empty_pattern_is_refused_naming_itself():                    # H2
    got = _parse({"syn_ok": "foo", "syn_empty": ""})
    assert got.startswith("refused:") and "syn_empty" in got and "empty" in got, got


def test_an_invalid_regex_is_refused_not_raised():                       # H3
    got = _parse({"syn_bad": "(unclosed"})
    assert got.startswith("refused:") and "unusable derivation pattern 'syn_bad'" in got, got


def forbidden_derivations(inv, figure, manifest):
    """The evaluator's helper; absent is an assertion, not a collection error."""
    fn = getattr(_inv, "forbidden_derivations", None)
    assert fn is not None, "kit_engine has no forbidden_derivations"
    return fn(inv, figure, manifest)


def _guard():
    kit = load_kit(BLOCKS / "rail")
    records = {i.id: i for i in kit.invariants}
    assert "INV-RAIL-DERIVATION-GUARD" in records, "rail declares no derivation guard"
    return kit, records["INV-RAIL-DERIVATION-GUARD"]


@pytest.mark.parametrize("text", [
    "THE SFT IS INFERRED FROM THE INSTALLATION TEMPERATURE",
    "The Sft Is Inferred From The Installation Temperature",
])
def test_pattern_match_ignores_case(text):                              # H4
    kit, inv = _guard()
    q = next(iter(kit.manifest.quantities))
    assert forbidden_derivations(inv, Figure(quantity=q, text=text), kit.manifest) == [
        "sft_from_installation_temperature"]


def test_a_host_named_derivation_is_still_refused_without_text():
    kit, inv = _guard()
    q = next(iter(kit.manifest.quantities))
    fig = Figure(quantity=q, text="", derivations=["twist_without_base_length"])
    assert forbidden_derivations(inv, fig, kit.manifest) == ["twist_without_base_length"]
    assert forbidden_derivations(inv, Figure(quantity=q, text=""), kit.manifest) == []


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
    kit, inv = _guard()
    q = next(iter(kit.manifest.quantities))
    hit = kit._one(inv, Figure(quantity=q, text=bad), [], None, (), None)
    assert hit is not None and hit.missing == [name]
    assert kit._one(inv, Figure(quantity=q, text=good), [], None, (), None) is None


def test_rail_derivation_guard_refuses_through_the_answer_hook():
    kit, _ = _guard()
    now = time.time()
    state = {n: {"as_of": now} for n in kit.manifest.state_providers}
    fig = Figure(quantity="sft", value=27, unit="degC", origin="document", source_id="syn",
                 text="the SFT is inferred from the installation temperature")
    out = kit.answer_time([fig], state=state, now=now)
    assert out.verdict == "refused"
    assert "INV-RAIL-DERIVATION-GUARD" in {f.invariant_id for f in out.findings}
