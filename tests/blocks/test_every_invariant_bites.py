"""Every invariant in every kit, proven to FIRE — by id, one test each.

The six kits built before the shared evaluator each carry a bespoke test file whose
stated contract is "every block-severity invariant has a test that triggers it".
The other eleven had no equivalent: the shared suite
(``test_reasoning_kits.py``) proves cross-kit properties per kit — a scope refusal
comes before retrieval, an undeclared qualifier is refused, every hook runs — but it
never proves that THIS kit's INV-FM-SLA can actually fire.

Load-time already refuses a record that could never fire
(``test_a_record_that_could_never_fire_refuses_to_load``). That is a static check on
the declaration. This is the behavioural one: for each of the 217 records, build the
figure that record exists to catch and assert THAT RECORD's id is in the findings.

Asserting by id matters. A test that only checks "something was refused" passes when
a different invariant fires first, which is how a rule that never fires hides inside
a suite that looks green — and this evaluator deliberately runs every rule, so
something almost always fires.

The trigger for each kind is derived from the record's own declaration, not
hand-written per kit:

  qualifier        a figure with none of the fields it `requires`
  grounding        a figure with no source at all
  band             a value outside the declared min/max
  unit_discipline  a figure with no unit
  authority        a figure citing a class the record demotes
  provenance       two figures whose `across` dimensions disagree
  currency         a figure whose state provider has no reading
  derivation       a figure stating arithmetic that does not hold
  scope            the question pattern, at H0, before retrieval
"""
from __future__ import annotations

import pathlib
import time
from typing import Any, Dict, List, Optional, Tuple

import pytest
import yaml

from app.blocks.kit_engine import Figure, load_kit

ROOT = pathlib.Path(__file__).resolve().parents[2]
BLOCKS = ROOT / "app" / "blocks"


def _kits() -> List[str]:
    return sorted(p.parent.name for p in BLOCKS.glob("*/manifest.yaml")
                  if (p.parent / "invariants.yaml").is_file())


def _records() -> List[Tuple[str, str, str]]:
    """(kit, invariant id, kind) for every record in the Store."""
    out: List[Tuple[str, str, str]] = []
    for kit in _kits():
        raw = yaml.safe_load((BLOCKS / kit / "invariants.yaml").read_text(encoding="utf-8")) or {}
        for record in raw.get("invariants") or []:
            out.append((kit, str(record["id"]), str(record.get("kind"))))
    return out


ALL_RECORDS = _records()

#: Loaded once per kit rather than per record: 217 loads of the same seventeen
#: files is 200 re-parses that prove nothing.
_CACHE: Dict[str, Any] = {}


def _kit(name: str):
    if name not in _CACHE:
        _CACHE[name] = load_kit(BLOCKS / name)
    return _CACHE[name]


def _record(kit, invariant_id: str) -> Any:
    for inv in kit.invariants:
        if inv.id == invariant_id:
            return inv
    raise AssertionError(f"{invariant_id} is not in the loaded kit")


def _first_quantity(kit, inv) -> str:
    """A quantity this record actually governs, so the trigger reaches it."""
    declared = list(kit.manifest.quantities)
    classes = kit.manifest.quantity_classes()
    for name in inv.quantities():
        if name in kit.manifest.quantities:
            return name
        if name == "any":
            return declared[0]
        if name.startswith("any_"):
            members = classes.get(name) or ()
            if members:
                return members[0]
    return declared[0]


def _unit_for(kit, quantity: str) -> Optional[str]:
    spec = kit.manifest.quantities.get(quantity)
    return spec.units[0] if spec and spec.units else None


def _raw(kit_name: str, invariant_id: str) -> Dict[str, Any]:
    raw = yaml.safe_load((BLOCKS / kit_name / "invariants.yaml").read_text(encoding="utf-8")) or {}
    for record in raw.get("invariants") or []:
        if str(record["id"]) == invariant_id:
            return record
    raise AssertionError(f"{invariant_id} not found in {kit_name}")


def _complete(kit, inv, quantity: str, raw_applies=None, **over) -> Figure:
    """A figure with everything the kit could want, so only the ONE defect we
    introduce is what fires. Built from the kit's own declarations."""
    qualifiers: Dict[str, Any] = {}
    for other in kit.invariants:
        if other.kind != "qualifier":
            continue
        for field in other.requires:
            spec = kit.manifest.qualifier_fields.get(field)
            if spec is None:
                qualifiers[field] = "stated"
            elif spec.type == "enum":
                qualifiers[field] = spec.values[0] if spec.values else "stated"
            elif spec.type == "date":
                qualifiers[field] = "2026-09-24"
            elif spec.type == "number":
                qualifiers[field] = 1
            elif spec.type == "bool":
                qualifiers[field] = False
            else:
                qualifiers[field] = "stated"
    governing = sorted(kit.manifest.source_classes.values(), key=lambda c: c.rank)
    base = dict(
        quantity=quantity,
        value=1.0,
        unit=_unit_for(kit, quantity),
        origin="document",
        source_id="doc-1",
        source_class=governing[0].name if governing else None,
        qualifiers=qualifiers,
        text=f"{quantity} is 1.0",
    )
    # A record may narrow itself to one claim class ("this rule is about a code
    # REQUIREMENT"). Without it the record does not govern the figure at all, and the
    # trigger silently reaches nothing — which reads in the results as "the invariant
    # never fires" when in fact it was never asked.
    narrowed = (raw_applies or {}).get("claim_class")
    if narrowed:
        base["claim_class"] = str(narrowed)
    base.update(over)
    return Figure(**base)


def _fresh_state(kit) -> Dict[str, Any]:
    now = time.time()
    return {name: {"as_of": now} for name in kit.manifest.state_providers}


def _sweep(kit, figures, state=None, events=()) -> List[str]:
    """Every invariant id that fired, across the whole routing map."""
    fired: List[str] = []
    for outcome in (kit.ranking(figures),
                    kit.tool_time(figures),
                    kit.answer_time(figures, state, events),
                    # H4 too. Some records are export-time ONLY -- INV-WT-CURRENCY is
                    # `hook: H4` -- so a sweep that stops at answer-time reports them
                    # as never firing when nothing has asked them yet.
                    kit.export_time(figures, state, events)):
        fired.extend(f.invariant_id for f in outcome.findings)
    return fired


# --------------------------------------------------------------------------

def test_the_record_sweep_is_honest():
    """Guards the parametrisation below: an empty or shrunken list would pass
    every test in this file silently."""
    assert len(ALL_RECORDS) >= 260, len(ALL_RECORDS)
    assert len({kit for kit, _, _ in ALL_RECORDS}) == len(_kits())
    assert len({i for _, i, _ in ALL_RECORDS}) == len(ALL_RECORDS), "duplicate ids"


@pytest.mark.parametrize(
    "kit_name,invariant_id,kind", ALL_RECORDS,
    ids=[f"{k}:{i}" for k, i, _ in ALL_RECORDS],
)
def test_the_invariant_fires_when_its_own_defect_is_present(kit_name, invariant_id, kind):
    kit = _kit(kit_name)
    inv = _record(kit, invariant_id)
    raw = _raw(kit_name, invariant_id)
    quantity = _first_quantity(kit, inv)

    if kind == "scope":
        # A scope record is the ONE kind whose id never appears in a finding, and
        # that is deliberate: `eval_scope` says "the patterns live in the MANIFEST's
        # scope_refusals; a scope record carries the severity and the measurement,
        # not patterns of its own", and it labels the finding `SCOPE:<label>`. So the
        # contract to prove is the record's actual one — every declared pattern
        # refuses at H0 with the record's severity — and the assertion that matters
        # is not that the answer says no, it is that NOTHING WAS SEARCHED.
        probes = _scope_probes(kit)
        assert probes, f"{kit_name} declares a scope invariant but no refusal patterns"
        for probe in probes:
            outcome = kit.pre_retrieval(probe)
            scope_findings = [f for f in outcome.findings if f.kind == "scope"]
            assert scope_findings, (
                f"{invariant_id}: {probe!r} is a declared refusal pattern and produced "
                f"no scope finding")
            assert outcome.verdict == "refused", f"{invariant_id} on {probe!r}"
            # `retrieval_permitted` is the BLOCK's field, not the engine Outcome's;
            # that nothing was retrieved is proven with a retrieval spy in
            # test_reasoning_kits.py::test_every_kit_refuses_its_scope_questions_
            # before_retrieval. Here the record's own contract is the subject.
            assert {f.severity for f in scope_findings} == {raw.get("severity")}
            for finding in scope_findings:
                assert finding.invariant_id.startswith("SCOPE:")
                assert "nothing was retrieved" in finding.message
        return

    figures, state, events = _trigger(kit, inv, raw, kind, quantity)
    fired = _sweep(kit, figures, state, events)
    assert invariant_id in fired, (
        f"{invariant_id} ({kind}) did not fire on a figure built to trigger it. "
        f"What did fire: {sorted(set(fired)) or 'nothing'}"
    )


def _scope_probes(kit) -> List[str]:
    """Questions matching the MANIFEST's refusal patterns, regexes made literal.

    A ``scope`` record carries a ``refusal_class`` and no pattern of its own: the
    patterns live in the manifest's ``scope_refusals``, and the record is what turns
    a match into a refusal. So the probe comes from the manifest, and every declared
    pattern is tried — a record that matched none of them would be a rule that
    cannot fire.
    """
    import re as _re

    probes: List[str] = []
    for refusal in kit.manifest.scope_refusals:
        probes.append(_literal(refusal.pattern))
    return [p for p in probes if p]


def _literal(pattern: str) -> str:
    """One concrete question that the pattern matches.

    Order matters and each step earned its place against a real pattern in the
    Store. `what\\s+hazard\\s+class(?:ification)?\\s+is\\s+this` became
    "what hazard class:ification is this" when optional groups were stripped by
    brute force, and `will\\s+this\\s+pass\\b|will\\s+it\\s+pass` needs the first
    alternative of a TOP-LEVEL alternation, not a mangled blend of both.
    """
    import re as _re

    text = pattern
    # 1. A top-level alternation offers whole alternatives; take the first.
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "|" and depth == 0:
            text = text[:index]
            break
    # 2. An OPTIONAL group is optional: drop it rather than inline it.
    while True:
        reduced = _re.sub(r"\((?:\?:)?[^()]*\)\?", "", text)
        if reduced == text:
            break
        text = reduced
    # 3. A required group offers alternatives; take the first.
    while True:
        reduced = _re.sub(r"\((?:\?:)?([^()|]*)(?:\|[^()]*)?\)", r"\1", text)
        if reduced == text:
            break
        text = reduced
    # 4. A character class offers single characters; take the first real one.
    #    `energi[sz]e` -> `energise`, `four[-\s]foot` -> `four-foot`.
    def _first_char(match):
        body = match.group(1)
        body = body.replace(r"\s", " ").replace(r"\d", "1").replace(r"\w", "a")
        return body[0] if body else ""

    text = _re.sub(r"\[([^\]]+)\]", _first_char, text)
    # 5. Whitespace classes become one space; zero-width assertions vanish.
    for token, replacement in ((r"\s+", " "), (r"\s*", " "), (r"\b", ""),
                               (r"\.", "."), (r"\d+", "1")):
        text = text.replace(token, replacement)
    text = text.replace("^", "").replace("$", "").replace("?", "")
    return _re.sub(r"\s+", " ", text).strip()


def _trigger(kit, inv, raw: Dict[str, Any], kind: str, quantity: str):
    """(figures, state, events) carrying exactly the defect this record catches."""
    state = _fresh_state(kit)

    if kind == "qualifier":
        return [_complete(kit, inv, quantity, raw_applies=(raw.get('applies_to') or {}), qualifiers={})], state, ()

    if kind == "grounding":
        return [_complete(kit, inv, quantity, raw_applies=(raw.get('applies_to') or {}), source_id=None, source_class=None,
                          origin="model")], state, ()

    if kind == "unit_discipline":
        # Three shapes. `forbid` names a unit family that must never appear;
        # `requires_one_of` names the only acceptable families, so anything else is
        # the defect; otherwise the defect is having no unit at all.
        forbidden = [str(f) for f in (raw.get("forbid") or ()) if str(f) != "mixed"]
        allowed = [str(u) for u in (raw.get("requires_one_of") or ())]
        if forbidden:
            bad = forbidden[0]
        elif allowed:
            bad = next((u for u in ("furlongs", "kips", "cubits") if u not in allowed))
        else:
            bad = None
        return ([_complete(kit, inv, quantity,
                           raw_applies=(raw.get('applies_to') or {}), unit=bad)],
                state, ())

    if kind == "band":
        band = raw.get("band") or {}
        high, low = band.get("max"), band.get("min")
        # `{min: present, max: present}` is a TWO-SIDEDNESS band, not a numeric
        # range: it demands both bounds, from one analysis. One-sided is the defect.
        if str(low) == "present" or str(high) == "present":
            return ([_complete(kit, inv, quantity, raw_applies=(raw.get('applies_to') or {}), bounds={"min": 1})], state, ())
        value = float(high) * 1000 + 1 if high is not None else float(low) - 1000
        return [_complete(kit, inv, quantity, raw_applies=(raw.get('applies_to') or {}), value=value)], state, ()

    if kind == "authority":
        demoted = list(raw.get("demote") or [])
        cited = demoted[0] if demoted else _weakest(kit)
        return [_complete(kit, inv, quantity, raw_applies=(raw.get('applies_to') or {}), source_class=cited)], state, ()

    if kind == "provenance":
        # Two shapes, and the record says which. `forbid` names derivations that must
        # never have produced the figure; `across` names dimensions a figure may not
        # be carried over, which the engine reads as the figure's own qualifier
        # disagreeing with what was ASKED about.
        forbidden = [str(f) for f in (raw.get("forbid") or ())]
        if forbidden:
            return [_complete(kit, inv, quantity, raw_applies=(raw.get('applies_to') or {}), derivations=[forbidden[0]])], state, ()
        across = [str(a) for a in (raw.get("across") or ())]
        figure = _complete(kit, inv, quantity, raw_applies=(raw.get('applies_to') or {}))
        dimension = across[0]
        if dimension == "revision":
            figure.revision = "rev-A"
            figure.asked_about = {"revision": "rev-B"}
        else:
            figure.qualifiers[dimension] = "here"
            figure.asked_about = {dimension: "somewhere-else"}
        return [figure], state, ()

    if kind == "currency":
        # No reading at all from the provider this record watches: state UNKNOWN.
        provider = ((raw.get("window") or {}).get("provider")
                    or (raw.get("applies_to") or {}).get("provider"))
        stale = dict(state)
        if provider:
            stale.pop(str(provider), None)
        else:
            stale = {}
        events = tuple(
            trigger for triggers in kit.manifest.staleness_triggers.values()
            for trigger in triggers
        )
        return [_complete(kit, inv, quantity, raw_applies=(raw.get('applies_to') or {}))], stale, events

    if kind == "derivation":
        # Stated arithmetic that does not hold, which is what `derivation` reads.
        figure = _complete(kit, inv, quantity, raw_applies=(raw.get('applies_to') or {}),
                           text=f"{quantity}: 2 + 2 = 5",
                           derivations=["2 + 2 = 5"],
                           steps=["2 + 2 = 5"])
        return [figure], state, ()

    raise AssertionError(f"no trigger defined for kind {kind!r}")


def _weakest(kit) -> Optional[str]:
    classes = sorted(kit.manifest.source_classes.values(), key=lambda c: -c.rank)
    return classes[0].name if classes else None
