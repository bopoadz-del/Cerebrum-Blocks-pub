"""Every kit must be able to say YES to something.

``test_every_invariant_bites.py`` proves each of the ~220 records in the Store can
FIRE. ``test_reasoning_kits.py`` proves cross-kit refusal properties. Both of them,
and every per-kit suite, pass in full against a kit that refuses absolutely
everything.

That is not a hypothetical. A kit is a few hundred lines of declaration; one
qualifier record applying to ``any`` with a field no figure can carry turns the
whole kit into a wall, and the symptom is a platform that answers nothing while
reporting fail-closed — which reads as correct, careful behaviour. It is the same
shape as every other defect this layer has produced: the failure and the success
look identical from outside, so only a test that demands a PASS can separate them.

So: for each kit, build a figure from the kit's OWN declaration that ought to
satisfy it, and assert at least one quantity gets through all four hooks.

Why "at least one" and not "all": the satisfier below is derived mechanically from
the declaration, and some records cannot be satisfied mechanically without encoding
domain knowledge the declaration does not carry — a derivation record wants
arithmetic that holds, a provenance record wants sibling figures that agree. A test
that demanded all of them would be asserting the satisfier's cleverness, not the
kit's behaviour, and would go red for reasons that are not defects. One quantity
passing is the whole anti-wall claim: a kit that refuses everything cannot produce
it, and a kit that gates properly always can.

WHAT THIS DOES NOT CATCH, established by running the control both ways rather than
assumed. The satisfier invents a value for any ``requires`` field, declared in the
manifest or not, so a record demanding a field nothing could supply does NOT trip
this test. That was the first control tried here and it passed, which is the only
reason the limit is written down.

The shape it does catch is CONTRADICTION between records — a unit forbidden by one
record and required by another, two authority records naming different governing
classes for the same quantity, a band that cannot be satisfied. Verified by
injecting a ``unit_discipline`` record forbidding every unit its kit declares:
all six fitout quantities then refused and this suite failed, naming the record.
That is the realistic wall, because a single demanding qualifier is something a
host can always choose to supply, and mutually exclusive records are something no
host can satisfy at any price.
"""
from __future__ import annotations

import pathlib
import time
from typing import Any, Dict, List, Tuple

import pytest
import yaml

from app.blocks.kit_engine import Figure, load_kit

BLOCKS = pathlib.Path(__file__).resolve().parents[2] / "app" / "blocks"


def _kits() -> List[str]:
    return sorted(p.parent.name for p in BLOCKS.glob("*/manifest.yaml")
                  if (p.parent / "invariants.yaml").is_file())


def _qualifier_value(spec: Dict[str, Any], name: str) -> Any:
    """A value this field would actually accept, from its own declaration.

    Enums get their first declared member, because a value outside the enum is a
    different refusal and would make a passing test impossible for the wrong reason.
    """
    values = spec.get("values")
    if values:
        return values[0]
    kind = spec.get("type")
    if kind == "number":
        return 1.0
    if kind == "date":
        return "2026-09-01"
    if kind == "boolean":
        return False
    return f"{name}-1"


def _satisfying(kit, raw: Dict[str, Any], quantity: str) -> Tuple[Figure, Dict[str, Any]]:
    """The figure this kit's own records say would be acceptable for *quantity*."""
    probe = Figure(quantity=quantity)
    governing = [inv for inv in kit.invariants
                 if inv.kind != "scope" and inv.governs(probe)]

    qualifier_fields = raw.get("qualifier_fields") or {}
    qualifiers: Dict[str, Any] = {}
    source_class = None
    banded = False
    for inv in governing:
        for field in inv.requires or ():
            qualifiers[field] = _qualifier_value(qualifier_fields.get(field) or {}, field)
        for field in inv.requires_any_of or ():
            qualifiers[field] = _qualifier_value(qualifier_fields.get(field) or {}, field)
        for governs_as in inv.governing or ():
            source_class = source_class or governs_as
        if inv.kind == "band":
            banded = True

    units = ((raw.get("quantities") or {}).get(quantity) or {}).get("units") or []
    moment = time.time()
    # Every declared provider reads cleanly. A provider that cannot be read is
    # UNKNOWN by design, so leaving them out would be testing the currency records
    # rather than whether the kit can ever pass.
    state = {name: {"as_of": moment, "value": "ok"}
             for name in (raw.get("state_providers") or {})}

    figure = Figure(
        quantity=quantity, value=1, unit=(units[0] if units else None),
        origin="document", source_id="DOC-1", source_class=source_class,
        revision="A", effective_date="2026-09-01", qualifiers=qualifiers,
    )
    if banded:
        # A banded quantity is refused when given one side, correctly: "one side of
        # a band is not a conservative answer". Supply both, or this satisfier
        # would be asserting the band record instead of the kit's ability to pass.
        figure.bounds = {"min": 1, "max": 2,
                         "source_id_min": "DOC-1", "source_id_max": "DOC-1"}
    return figure, state


def _verdicts(kit, figure: Figure, state: Dict[str, Any]) -> List[Tuple[str, Any]]:
    return [
        ("H1", kit.ranking([figure])),
        ("H2", kit.tool_time([figure])),
        ("H3", kit.answer_time([figure], state, [])),
        ("H4", kit.export_time([figure], state, [])),
    ]


@pytest.mark.parametrize("kit_name", _kits())
def test_the_kit_can_say_yes_to_at_least_one_quantity(kit_name):
    """The anti-wall guarantee.

    If this fails, the kit refuses every figure it governs — and every refusal
    test for it still passes, so nothing else in this repository would tell you.
    """
    kit = load_kit(BLOCKS / kit_name)
    raw = yaml.safe_load((BLOCKS / kit_name / "manifest.yaml").read_text(encoding="utf-8"))

    satisfied: List[str] = []
    refusals: Dict[str, List[str]] = {}
    for quantity in (raw.get("quantities") or {}):
        figure, state = _satisfying(kit, raw, quantity)
        blocked = [f"{hook}:{finding.invariant_id}"
                   for hook, outcome in _verdicts(kit, figure, state)
                   for finding in outcome.findings if finding.severity == "refuse"]
        if blocked:
            refusals[quantity] = sorted(set(blocked))
        else:
            satisfied.append(quantity)

    assert satisfied, (
        f"kit '{kit_name}' refused a figure built from its own declaration for "
        f"EVERY one of its {len(refusals)} quantities. It is a wall, not a gate: "
        f"a platform built on it answers nothing while reporting fail-closed. "
        f"First refusals: "
        + "; ".join(f"{q} -> {ids}" for q, ids in list(refusals.items())[:3])
    )


@pytest.mark.parametrize("kit_name", _kits())
def test_the_satisfying_figure_was_actually_governed(kit_name):
    """Guard on the guard: a pass proves nothing if no record was looking.

    A quantity no invariant governs passes trivially, which would let the test
    above go green for a kit whose records had all stopped matching — the exact
    shape of the H4 routing defect, where records declared at H4 were selected at
    no hook and every H4 outcome was a vacant pass.
    """
    kit = load_kit(BLOCKS / kit_name)
    raw = yaml.safe_load((BLOCKS / kit_name / "manifest.yaml").read_text(encoding="utf-8"))

    best = 0
    for quantity in (raw.get("quantities") or {}):
        figure, state = _satisfying(kit, raw, quantity)
        if any(outcome.findings and any(f.severity == "refuse" for f in outcome.findings)
               for _, outcome in _verdicts(kit, figure, state)):
            continue
        governing = [inv for inv in kit.invariants
                     if inv.kind != "scope" and inv.governs(figure)]
        best = max(best, len(governing))

    assert best >= 2, (
        f"the quantity that passes in kit '{kit_name}' is governed by only {best} "
        f"record(s), so the anti-wall test above is measuring almost nothing"
    )
