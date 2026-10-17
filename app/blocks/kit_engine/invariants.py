"""The eight invariant kinds, plus `band`. One implementation each, shared by
every kit. Nothing here knows what a runway or a slab is.

  grounding        does this figure exist in evidence?                    H3
  qualifier        is it accompanied by what makes it actionable?          H3
  unit_discipline  are unit and datum stated, and not mixed?          H2 + H3
  authority        does it come from the class of source that governs?     H1
  provenance       was it carried from another entity or revision?        H3
  currency         has the thing that invalidates it happened?            H3
  scope            is the question answerable from documents at all?      H0
  derivation       do the stated working and the stated result agree?     H3
  band             is the value possible / is it two-sided?               H2

Each kind exists because a defect of that shape shipped to a live product and
was caught by counting, not by review.

HOOKS. The spec's routing map (§2) fixes a hook per kind. A record may state its
`hook:` explicitly, and the loader accepts it only when it is that kind's spec
hook -- or H4, which by definition re-runs the H3 checks on the deliverable.
Anything else is a load failure naming the table, because silently relocating a
rule to a hook the host never calls is how a kit reports green while gating
nothing.

MEASUREMENT. Spec §4: "No invariant SHIPS without a measurement case." The word
is *ships*, and §5 puts the AC tests in the kit's own ``tests/``. So a record
with no ``measurement:`` LOADS, ``Kit.unmeasured`` names it, and the ship gate
(certification and signing) is where it bites.

SCOPE. Correction 1: the refusal patterns live in the MANIFEST. A `scope` record
carries the severity and the measurement, not patterns of its own.

Two rules hold in every domain and are enforced here, not left to kit authors:

  * **Never refuse the operator's own figure.** If they typed the rate it is
    authoritative input, not a claim to check: the severity softens to `flag`
    and the finding records what it was softened from.
  * A finding names the invariant AND what is missing. "Blocked" on its own
    teaches the caller nothing and gets the layer switched off.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.blocks.kit_engine.figure import Figure, Finding, SEVERITIES
from app.blocks.kit_engine.manifest import Manifest

KINDS = (
    "grounding", "qualifier", "unit_discipline", "authority",
    "provenance", "currency", "scope", "derivation", "band",
)

H0_PRE_RETRIEVAL = "H0"
H1_RANKING = "H1"
H2_TOOL_TIME = "H2"
H3_ANSWER_TIME = "H3"
H4_EXPORT_TIME = "H4"

#: The spec's routing map. unit_discipline runs at TWO hooks on purpose: H2
#: alone misses figures the model states without a tool; H3 alone lets a
#: corrupted value reach exports and source panels before anyone checks.
HOOKS_BY_KIND: Dict[str, Tuple[str, ...]] = {
    "scope": (H0_PRE_RETRIEVAL,),
    "authority": (H1_RANKING,),
    "unit_discipline": (H2_TOOL_TIME, H3_ANSWER_TIME),
    "band": (H2_TOOL_TIME,),
    "grounding": (H3_ANSWER_TIME,),
    "qualifier": (H3_ANSWER_TIME,),
    "provenance": (H3_ANSWER_TIME,),
    "currency": (H3_ANSWER_TIME,),
    "derivation": (H3_ANSWER_TIME,),
}

#: Kinds whose evaluator actually calls ``state_precondition``. ``requires_state``
#: declared on any other kind is INERT — the field parses, the record reads as a
#: live-state gate, and nothing ever checks the state.
#:
#: That is the most dangerous kind of decoration this format can carry. A dead
#: qualifier over-refuses and somebody notices within a day; a dead STATE gate
#: under-refuses, silently, and the figure is asserted with the state UNKNOWN —
#: which is the one outcome ``state_precondition``'s own docstring says must never
#: happen ("an unreachable source yields UNKNOWN, never a fallback to the design
#: basis"). ``stadium_venue`` shipped seven of them: exit doors, gates, PA,
#: scoreboard, host venue cooperation, roof position and open stands, all declared,
#: none enforced, and a licensed capacity could be stated without knowing which
#: stands were open.
#:
#: ``test_state_aware_kinds_matches_the_evaluators_that_read_state`` asserts this
#: set against the source of every ``eval_*`` function, so it cannot drift from
#: which code actually reads the field — the drift being exactly how the original
#: hole opened.
STATE_AWARE_KINDS: frozenset = frozenset({"currency", "derivation"})


def legal_hooks(kind: str, band: Optional[Dict[str, Any]] = None) -> Tuple[str, ...]:
    """Hooks a record of *kind* may declare.

    H4 re-runs H3, so any H3 kind may also name H4 -- that is the export-time
    pass, not a relocation.

    `band` is two rules wearing one name, and they belong at different hooks.
    §2 puts band at H2 because "an impossible value reaches every downstream
    consumer" -- that is the POSSIBILITY band, and it must be caught where the
    value is born. A TWO-SIDEDNESS band (`min: present, max: present`) is not
    about an impossible value at all: it is about the ANSWER being single-sided,
    which is an answer-time property and cannot be seen at tool time, because at
    tool time there is one figure and no answer yet. So a presence-band may
    declare H3 (and H4); a numeric band may not.
    """
    hooks = HOOKS_BY_KIND[kind]
    if kind == "band" and band and (
        str(band.get("min")) == "present" or str(band.get("max")) == "present"
    ):
        hooks = hooks + (H3_ANSWER_TIME,)
    return hooks + (H4_EXPORT_TIME,) if H3_ANSWER_TIME in hooks else hooks


class InvariantError(ValueError):
    """An invariant record is not usable. The kit is disabled, and refuses."""


@dataclass
class Invariant:
    id: str
    kind: str
    severity: str
    applies_to: Dict[str, Any] = field(default_factory=dict)
    hook: Optional[str] = None
    requires: Tuple[str, ...] = ()
    requires_one_of: Tuple[str, ...] = ()
    requires_any_of: Tuple[str, ...] = ()
    requires_steps: Tuple[str, ...] = ()
    requires_state: Tuple[str, ...] = ()
    block_if_missing_state: bool = False
    block_if: Tuple[str, ...] = ()
    forbid: Tuple[str, ...] = ()
    across: Tuple[str, ...] = ()
    band: Dict[str, Any] = field(default_factory=dict)
    window: Dict[str, Any] = field(default_factory=dict)
    governing: Tuple[str, ...] = ()
    fallback_class: Optional[str] = None
    demote: Tuple[str, ...] = ()
    require_qualifier: Optional[str] = None
    trigger_source: Optional[str] = None
    refusal_class: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    measurement: str = ""
    _classes: Dict[str, Tuple[str, ...]] = field(default_factory=dict, repr=False)

    def hooks(self) -> Tuple[str, ...]:
        return (self.hook,) if self.hook else HOOKS_BY_KIND[self.kind]

    def quantities(self) -> Tuple[str, ...]:
        raw = self.applies_to.get("quantity")
        if raw is None:
            return ()
        return (str(raw),) if isinstance(raw, str) else tuple(str(q) for q in raw)

    def claim_class(self) -> Optional[str]:
        value = self.applies_to.get("claim_class")
        return str(value) if value else None

    def governs(self, figure: Figure) -> bool:
        """Does this invariant govern *figure*?

        ``any_*`` is a CLASS the manifest defines, never a wildcard: the first
        cut treated it as match-all and the units-and-datum record then demanded
        a vertical datum for a PCN, which has neither. ``any`` alone means every
        quantity, spelled out.

        A ``claim_class`` narrows further, and a figure carrying no claim class
        does not match a record that names one -- guessing the claim class from
        prose is the defect, not the fix.
        """
        wanted = self.quantities()
        matched = not wanted or wanted == ("any",)
        if not matched:
            for name in wanted:
                if name == figure.quantity:
                    matched = True
                    break
                if name.startswith("any_") and figure.quantity in self._classes.get(name, ()):
                    matched = True
                    break
        if not matched:
            return False
        wanted_class = self.claim_class()
        if wanted_class and figure.claim_class != wanted_class:
            return False
        return True


def _text(inv: Invariant, computed: str) -> str:
    """The kit's declared message is a HEADLINE, not a replacement.

    The first cut used ``inv.message or computed``, so any kit that declared a
    message silently DISCARDED the specifics -- which facility the figure came
    from, which equation disagreed with its own result. That is the "blocked
    teaches the caller nothing" failure, in the evaluator itself.
    """
    headline = (inv.message or "").strip()
    computed = (computed or "").strip()
    if not headline:
        return computed
    if not computed:
        return headline
    return f"{headline} [{computed}]"


def _render(message: str, missing: Sequence[str], figure: Optional[Figure] = None) -> str:
    """Correction 6: only {missing} and {value} are placeholders."""
    listed = ", ".join(missing) if missing else ""
    text = message.replace("{missing}", listed or "its qualifiers")
    if figure is not None and figure.value is not None:
        text = text.replace("{value}", str(figure.value))
    else:
        text = text.replace("{value}", listed or "the figure")
    if figure is not None:
        text = text.replace("{quantity}", figure.quantity)
    return text


#: Every key ``parse_invariant`` consumes, DERIVED from the dataclass rather than
#: hand-listed, plus the one alias the parser accepts (``governing_class`` for
#: ``governing``). Hand-listing it would be the same fact in two places, and the
#: place it would drift from is the one that decides behaviour.
#:
#: Why this exists: a key the parser does not read was silently DISCARDED. A record
#: could carry ``cross_check: [a, b]`` or ``require_qualifiers: [...]`` and load
#: clean, gating nothing, reporting green. Six invariants in the Store already carry
#: a dead ``applies_to.spec_extension`` that has never done anything.
def _allowed_invariant_keys() -> frozenset:
    from dataclasses import fields as _fields

    return frozenset(
        {f.name for f in _fields(Invariant) if not f.name.startswith("_")}
        | {"governing_class"}
    )


#: The only ``applies_to`` keys the engine reads. ``quantity`` selects what the
#: record governs; ``claim_class`` narrows it to one kind of claim. Anything else is
#: decoration that reads as a narrowing and is not one.
ALLOWED_APPLIES_TO_KEYS = frozenset({"quantity", "claim_class"})


def _refuse_unknown_keys(raw: Dict[str, Any], inv_id: str, where: str) -> None:
    allowed = _allowed_invariant_keys()
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise InvariantError(
            f"{where}: {inv_id} declares key(s) this engine does not read: "
            f"{', '.join(unknown)}. A key the parser discards gates NOTHING while the "
            f"record loads clean and reports green. Use one of: "
            f"{', '.join(sorted(allowed))}"
        )
    unknown_applies = sorted(set(raw.get("applies_to") or {}) - ALLOWED_APPLIES_TO_KEYS)
    if unknown_applies:
        raise InvariantError(
            f"{where}: {inv_id} declares applies_to key(s) this engine does not read: "
            f"{', '.join(unknown_applies)}. Only {', '.join(sorted(ALLOWED_APPLIES_TO_KEYS))} "
            f"select what a record governs; anything else reads as a narrowing and is not one"
        )


def parse_invariant(raw: Any, classes: Dict[str, Tuple[str, ...]], where: str) -> Invariant:
    """Parse one invariant record. Every rejection prevents a silent no-op."""
    if not isinstance(raw, dict):
        raise InvariantError(f"{where}: an invariant must be a mapping")
    inv_id = str(raw.get("id") or "").strip()
    if not inv_id:
        raise InvariantError(f"{where}: an invariant must declare an id")
    # Before anything is interpreted: a key this engine does not read is refused,
    # naming the key and the record. Checked here, ahead of the per-kind rules, so a
    # typo in a key cannot be reported as a missing field somewhere else.
    _refuse_unknown_keys(raw, inv_id, where)
    kind = str(raw.get("kind") or "").strip()
    if kind not in KINDS:
        raise InvariantError(
            f"{where}: {inv_id} has kind {kind!r}; expected one of {', '.join(KINDS)}"
        )
    severity = str(raw.get("severity") or "").strip()
    if severity not in SEVERITIES:
        raise InvariantError(
            f"{where}: {inv_id} has severity {severity!r}; expected one of "
            f"{', '.join(SEVERITIES)}"
        )
    hook = raw.get("hook")
    if hook is not None:
        hook = str(hook).strip()
        if hook not in legal_hooks(kind, raw.get("band")):
            raise InvariantError(
                f"{where}: {inv_id} declares hook {hook!r}, but a {kind} invariant runs "
                f"at {', '.join(legal_hooks(kind))} per the routing map. Relocating a rule "
                f"to a hook the host does not call makes the kit report green while "
                f"gating nothing"
            )

    governing = raw.get("governing") or raw.get("governing_class")
    governing_t = (
        (str(governing),) if isinstance(governing, str)
        else tuple(str(c) for c in (governing or ()))
    )

    inv = Invariant(
        id=inv_id,
        kind=kind,
        severity=severity,
        applies_to=dict(raw.get("applies_to") or {}),
        hook=hook,
        requires=tuple(str(f) for f in (raw.get("requires") or ())),
        requires_one_of=tuple(str(f) for f in (raw.get("requires_one_of") or ())),
        requires_any_of=tuple(str(f) for f in (raw.get("requires_any_of") or ())),
        requires_steps=tuple(str(f) for f in (raw.get("requires_steps") or ())),
        requires_state=tuple(str(f) for f in (raw.get("requires_state") or ())),
        block_if_missing_state=bool(raw.get("block_if_missing_state", False)),
        block_if=tuple(str(f) for f in (raw.get("block_if") or ())),
        forbid=tuple(str(f) for f in (raw.get("forbid") or ())),
        across=tuple(str(f) for f in (raw.get("across") or ())),
        band=dict(raw.get("band") or {}),
        window=dict(raw.get("window") or {}),
        governing=governing_t,
        fallback_class=str(raw["fallback_class"]) if raw.get("fallback_class") else None,
        demote=tuple(str(c) for c in (raw.get("demote") or ())),
        require_qualifier=str(raw["require_qualifier"]) if raw.get("require_qualifier") else None,
        trigger_source=str(raw["trigger_source"]) if raw.get("trigger_source") else None,
        refusal_class=str(raw["refusal_class"]) if raw.get("refusal_class") else None,
        evidence=dict(raw.get("evidence") or {}),
        message=str(raw.get("message") or ""),
        measurement=str(raw.get("measurement") or "").strip(),
        _classes=classes,
    )

    # A record that could never fire reports green while gating nothing.
    if kind == "qualifier" and not (inv.requires or inv.requires_any_of or inv.requires_one_of):
        raise InvariantError(f"{where}: {inv_id} is a qualifier invariant requiring no fields")
    if kind == "unit_discipline" and not (inv.requires_one_of or inv.forbid or inv.requires):
        raise InvariantError(
            f"{where}: {inv_id} must declare requires_one_of, requires or forbid"
        )
    if kind == "provenance" and not (inv.across or inv.forbid):
        raise InvariantError(
            f"{where}: {inv_id} must name the dimensions a figure may not cross, or the "
            f"forbidden derivations by name"
        )
    if kind == "currency" and not inv.window.get("provider"):
        raise InvariantError(f"{where}: {inv_id} must name a state provider in window")
    if kind == "band" and inv.band.get("min") is None and inv.band.get("max") is None:
        raise InvariantError(f"{where}: {inv_id} declares no band min or max")
    if kind == "authority" and not inv.governing:
        raise InvariantError(f"{where}: {inv_id} must name the governing source class(es)")
    # NOTE: a `derivation` record needs NO declared condition. Its baseline is
    # the spec's own definition of the kind -- "do the stated working and the
    # stated result agree?" -- which is arithmetic consistency plus
    # self-contradiction between sibling figures, and neither is declared. An
    # earlier version demanded block_if/forbid/requires_* here and disabled three
    # kits whose derivation records were perfectly correct.
    for wanted in inv.quantities():
        if wanted.startswith("any_") and wanted not in classes:
            raise InvariantError(
                f"{where}: {inv_id} applies to class '{wanted}', which no quantity "
                f"declares. An invariant that matches nothing is a decoration"
            )
    # An inert live-state gate UNDER-refuses in silence, so it must not be
    # declarable. See STATE_AWARE_KINDS for how this hole opened.
    if inv.requires_state:
        if kind not in STATE_AWARE_KINDS:
            raise InvariantError(
                f"{where}: {inv_id} declares requires_state on kind '{kind}', which "
                f"never reads it — only {', '.join(sorted(STATE_AWARE_KINDS))} call "
                f"state_precondition. Move the state gate to one of those kinds, or "
                f"the figure is asserted with {', '.join(inv.requires_state)} UNKNOWN"
            )
        if not inv.block_if_missing_state:
            raise InvariantError(
                f"{where}: {inv_id} declares requires_state "
                f"({', '.join(inv.requires_state)}) without block_if_missing_state, "
                f"so state_precondition returns before checking it. Arm it with "
                f"block_if_missing_state: true, or drop the requirement"
            )
    return inv


def _finding(
    inv: Invariant, figure: Optional[Figure], message: str, missing: Sequence[str] = ()
) -> Finding:
    """Compose the headline, render the placeholders, then apply the
    never-refuse-the-operator rule. Done here once so no evaluator can skip it."""
    message = _render(_text(inv, message), missing, figure)
    severity = inv.severity
    softened = None
    if figure is not None and figure.is_operators_own and severity == "refuse":
        severity, softened = "flag", inv.severity
        message = (
            message
            + " — flagged, not refused: this is the operator's own figure, which is "
            "authoritative input rather than a claim to check"
        )
    return Finding(
        invariant_id=inv.id,
        kind=inv.kind,
        severity=severity,
        message=message,
        quantity=figure.quantity if figure else "",
        missing=list(missing),
        span=dict(figure.span) if (figure and figure.span) else None,
        softened_from=softened,
    )


# ------------------------------------------------ shared state precondition --

def state_precondition(
    inv: Invariant, figure: Figure, state: Optional[Dict[str, Any]]
) -> Optional[Finding]:
    """``requires_state`` + ``block_if_missing_state``, usable by any kind.

    An unreachable source yields UNKNOWN, never a fallback to the design basis:
    a design figure presented as a current state is the defect this exists to
    stop, so the refusal names the sources and says nothing about the figure.
    """
    if not inv.requires_state or not inv.block_if_missing_state:
        return None
    records = state or {}
    missing = [name for name in inv.requires_state if records.get(name) is None]
    if not missing:
        return None
    detail = "state UNKNOWN — " + ", ".join(missing) + " unavailable"
    if len(inv.requires_state) > 1:
        detail += f"; all of {', '.join(inv.requires_state)} are required"
    return _finding(inv, figure, detail + ". Live state has no design-basis fallback", missing)


# ---------------------------------------------------------------- grounding --

def eval_grounding(inv: Invariant, figure: Figure, manifest: Manifest) -> Optional[Finding]:
    """A figure the model produced with no source is an invented figure.
    Live: "a rate nobody supplied". ``operator`` origin is exempt by definition."""
    if figure.origin == "operator":
        return None
    if figure.origin in ("document", "tool") and figure.source_id:
        return None
    return _finding(
        inv, figure,
        f"{figure.quantity} is not grounded: origin is {figure.origin} with no source_id. "
        f"A figure nobody supplied is invented",
        ["source_id"],
    )


# ---------------------------------------------------------------- qualifier --

def eval_qualifier(inv: Invariant, figure: Figure, manifest: Manifest) -> Optional[Finding]:
    missing = figure.missing(inv.requires)
    if inv.requires_any_of and not any(figure.known(f) for f in inv.requires_any_of):
        missing = missing + [f"one of {', '.join(inv.requires_any_of)}"]
    if not missing:
        return None
    return _finding(
        inv, figure,
        f"a {figure.quantity} figure without {', '.join(missing)} cannot be acted on",
        missing,
    )


# ---------------------------------------------------------- unit_discipline --

_BARE_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?![\w.%])")
_UNIT_NEAR_NUMBER = re.compile(
    r"-?\d[\d,]*(?:\.\d+)?\s*(?:mm|cm|m|km|ft|in|nm|kg|t|kN|kPa|MPa|psi|psig|barg|bara|bar|%|pct|"
    r"days?|hours?|h|min|s|deg|°|mg/l|mgL|ppm|IU|Ncm|rpm|kV|mA|units?|tiers?|NTU|kt|log)\b",
    re.IGNORECASE,
)
_UNIT_TOKEN = re.compile(
    r"-?\d[\d,]*(?:\.\d+)?\s*(mm|m|ft|metres|meters|feet|in|inches)\b", re.IGNORECASE
)
_UNIT_NORMAL = {
    "mm": "mm", "m": "m", "metres": "m", "meters": "m",
    "ft": "ft", "feet": "ft", "in": "in", "inches": "in",
}

DATUM_FAMILIES: Dict[str, Tuple[str, ...]] = {
    "vertical": ("AMSL_m", "AMSL_ft", "AOD", "chart datum", "berth datum",
                 "chart_datum", "berth_datum", "LAT", "MHWS"),
    "horizontal": ("WGS-84", "WGS84", "local grid", "national grid"),
    "bearing": ("magnetic", "true"),
}
DATUM_UNITS: Dict[str, str] = {"AMSL_m": "m", "AMSL_ft": "ft"}


def _datum_unit_conflict(figure: Figure) -> Optional[str]:
    """The figure's unit disagrees with the unit its datum names.

    The well-qualified-but-wrong case: a unit IS present and a datum IS present,
    and they contradict. An elevation in feet against a metre datum reads as
    complete and is not the height it looks like.
    """
    for name, value in figure.qualifiers.items():
        expected = DATUM_UNITS.get(str(value))
        if expected is None:
            continue
        stated = []
        if figure.unit:
            stated.append(_UNIT_NORMAL.get(str(figure.unit).lower(), str(figure.unit).lower()))
        for match in _UNIT_TOKEN.finditer(figure.text or ""):
            stated.append(_UNIT_NORMAL[match.group(1).lower()])
        wrong = sorted({u for u in stated if u in ("m", "ft", "mm", "in") and u != expected})
        if wrong:
            return f"{', '.join(wrong)} quoted against {name}={value}"
    return None


def _mixed_datum(text: str) -> Optional[str]:
    lowered = (text or "").lower()
    for family, members in DATUM_FAMILIES.items():
        present = {m for m in members if m.lower() in lowered}
        if len(present) >= 2:
            return f"{family}: {', '.join(sorted(present))}"
    return None


def eval_unit_discipline(
    inv: Invariant, figure: Figure, manifest: Manifest
) -> Optional[Finding]:
    if inv.requires:
        missing = figure.missing(inv.requires)
        if missing:
            return _finding(inv, figure, f"{figure.quantity} without {', '.join(missing)}", missing)

    if "mixed_datum" in inv.forbid or "mixed" in inv.forbid:
        conflict = _datum_unit_conflict(figure)
        if conflict:
            return _finding(inv, figure, f"mixed datum: {conflict}")
        mixed = _mixed_datum(figure.text)
        if mixed:
            return _finding(
                inv, figure,
                f"two datums in one statement ({mixed}) — a figure carries one datum or "
                f"it cannot be compared to anything",
            )

    # The unit must be one the kit declares legal for this quantity. Live: a
    # slab calculator bound metres to a millimetre parameter and returned
    # `0.2 mm` with status success.
    spec = manifest.quantities.get(figure.quantity)
    if spec and spec.units and figure.unit and figure.unit not in spec.units:
        return _finding(
            inv, figure,
            f"unit {figure.unit!r} is not legal for {figure.quantity} (expected one of "
            f"{', '.join(spec.units)})", ["unit"],
        )

    if inv.requires_one_of:
        haystack = (figure.text or "").lower()
        values = {str(v).lower() for v in figure.qualifiers.values() if v is not None}
        if figure.unit:
            values.add(str(figure.unit).lower())
        if not any(t.lower() in haystack or t.lower() in values for t in inv.requires_one_of):
            return _finding(
                inv, figure, "none of " + ", ".join(inv.requires_one_of) + " stated",
                list(inv.requires_one_of),
            )

    if ("bare_number" in inv.forbid or "unspecified" in inv.forbid) and not figure.unit:
        if _BARE_NUMBER.search(figure.text or "") and not _UNIT_NEAR_NUMBER.search(figure.text or ""):
            return _finding(
                inv, figure,
                "bare number — every figure carries its unit; a number whose unit the "
                "reader must guess is how metres become millimetres", ["unit"],
            )
    return None


# ---------------------------------------------------------------- authority --

def eval_authority(inv: Invariant, figure: Figure, manifest: Manifest) -> Optional[Finding]:
    """The figure must come from the class of source that governs.

    Live: a site-office mobilisation statement answering a specification
    question. The ladder is in the manifest; ``reject_as_proof`` says which class
    may not stand in for which; ``demote`` names classes this record refuses
    outright however they rank; ``require_qualifier`` is the qualifier without
    which the class means nothing (brand, for a neuromodulator unit).
    """
    if inv.require_qualifier and not figure.known(inv.require_qualifier):
        return _finding(
            inv, figure,
            f"{figure.quantity} carries no {inv.require_qualifier}, so its source class "
            f"cannot mean anything", [inv.require_qualifier],
        )
    if figure.source_class is None:
        return _finding(
            inv, figure,
            f"{figure.quantity} carries no source class, so it cannot be ranked against "
            f"the class that governs ({', '.join(inv.governing)})", ["source_class"],
        )
    # DECLARED order, not sorted. The record names the governing class first and
    # the fallback second; sorting alphabetically made the refusal cite whichever
    # class happened to sort first, which is not the one that governs.
    accepted = list(inv.governing) + ([inv.fallback_class] if inv.fallback_class else [])
    if figure.source_class in accepted:
        return None
    if figure.source_class in inv.demote:
        return _finding(
            inv, figure,
            f"a {figure.source_class} is demoted for {figure.quantity}: "
            f"{' or '.join(accepted)} governs",
        )
    mine = manifest.source_classes.get(figure.source_class)
    for name in accepted:
        governing = manifest.source_classes.get(name)
        if governing is None:
            continue
        if figure.source_class in governing.reject_as_proof:
            return _finding(
                inv, figure,
                f"a {figure.source_class} is not proof of {figure.quantity}: {name} governs, "
                f"and {figure.source_class} is explicitly rejected as proof",
            )
        if mine is not None and mine.rank > governing.rank:
            return _finding(
                inv, figure,
                f"{figure.source_class} (rank {mine.rank}) is outranked by {name} "
                f"(rank {governing.rank}) for {figure.quantity}",
            )
    return None


# --------------------------------------------------------------- provenance --

_CARRY_VERB = re.compile(
    r"\bsame\b|\bapplies\b|\bapply\b|\bcarry\b|\bcarried\b|\breuse\b|\bas\s+well\b|"
    r"\bequivalent\b|\btransfer\b|\bsimilar\b|\banother\b",
    re.IGNORECASE,
)


def eval_provenance(inv: Invariant, figure: Figure, manifest: Manifest) -> Optional[Finding]:
    """Was the figure carried from another entity or revision?

    The check is NOT "this dimension appears twice". Naming the same runway twice
    is what a CORRECT answer looks like, and a mention-counting regex blocks it --
    that bug was written and fixed by hand in the first kit built this way.
    Carrying means the figure's OWN entity differs from the entity the question is
    about, two DISTINCT values appear with a carry verb, or the host reports a
    named forbidden derivation in ``figure.derivations``.

    Live: delay damages computed on another contract's amount.
    """
    named = [d for d in figure.derivations if d in inv.forbid]
    if named:
        return _finding(inv, figure, f"forbidden derivation: {', '.join(named)}", named)

    for dimension in inv.across:
        mine = figure.qualifiers.get(dimension)
        if dimension == "revision":
            mine = figure.revision if figure.revision is not None else mine
        theirs = figure.asked_about.get(dimension)
        if mine is not None and theirs is not None and str(mine) != str(theirs):
            return _finding(
                inv, figure,
                f"this figure belongs to {dimension}={mine}; the question is about "
                f"{dimension}={theirs}. A figure does not carry across {dimension}",
                [dimension],
            )

    text = figure.text or ""
    if _CARRY_VERB.search(text):
        for dimension in inv.across:
            values = _distinct_values(text, manifest.qualifier_fields.get(dimension))
            if len(values) >= 2:
                return _finding(
                    inv, figure,
                    f"carrying a figure across {dimension} ({' -> '.join(values[:2])}) is "
                    f"never allowed", [dimension],
                )
    return None


def _distinct_values(text: str, spec: Any) -> List[str]:
    if spec is None:
        return []
    found: List[str] = []
    if spec.type == "enum":
        for value in spec.values:
            if re.search(rf"\b{re.escape(str(value))}\b", text, re.IGNORECASE):
                if str(value) not in found:
                    found.append(str(value))
    elif spec.pattern:
        for match in re.finditer(spec.pattern, text):
            if match.group(0) not in found:
                found.append(match.group(0))
    return found


# ----------------------------------------------------------------- currency --

def eval_currency(
    inv: Invariant,
    figure: Figure,
    manifest: Manifest,
    state: Optional[Dict[str, Any]] = None,
    events: Optional[Sequence[str]] = None,
    now: Optional[float] = None,
) -> Optional[Finding]:
    """Has the thing that invalidates this figure happened?

    Currency is usually an EVENT, not a clock: "any valve operation", "any
    approved MOC". A provider that cannot be read yields UNKNOWN -- never a
    fallback to the design basis.
    """
    blocked = state_precondition(inv, figure, state)
    if blocked is not None:
        return blocked

    provider_name = str(inv.window.get("provider"))
    provider = manifest.state_providers.get(provider_name)
    if provider is None:
        return _finding(
            inv, figure,
            f"state provider '{provider_name}' is not declared by this kit, so currency "
            f"cannot be established", [provider_name],
        )

    record = (state or {}).get(provider_name)
    if record is None:
        return _finding(
            inv, figure,
            f"state UNKNOWN — {provider_name} unavailable. Live state has no design-basis "
            f"fallback: a design figure is not a current state", [provider_name],
        )

    if inv.trigger_source and figure.qualifiers.get(inv.trigger_source) is True:
        return _finding(
            inv, figure,
            f"{inv.trigger_source} is true — the record predates a disturbance",
            [inv.trigger_source],
        )

    triggers = set(manifest.staleness_triggers.get(figure.quantity, ()))
    happened = [e for e in (events or ()) if e in triggers]
    if happened:
        return _finding(
            inv, figure,
            f"{figure.quantity} is stale: " + ", ".join(happened)
            + " has happened since it was recorded", happened,
        )

    max_age = inv.window.get("max_age", provider.max_age)
    try:
        seconds = float(max_age)
    except (TypeError, ValueError):
        seconds = None
    if seconds is not None:
        import time as _time

        moment = now if now is not None else _time.time()
        as_of = record.get("as_of") if isinstance(record, dict) else None
        if as_of is None or (moment - float(as_of)) > seconds:
            return _finding(
                inv, figure,
                f"{provider_name} record is older than its {seconds:g}s validity",
                [provider_name],
            )
    return None


# -------------------------------------------------------------------- scope --

def eval_scope(manifest: Manifest, question: str, severity: str = "refuse") -> Optional[Finding]:
    """Classify the question BEFORE retrieval.

    Correction 1: the patterns live in the MANIFEST's ``scope_refusals``; a scope
    record carries the severity and the measurement, not patterns of its own. No
    document makes an operational-authority question answerable, so retrieving at
    all is wrong -- it produces citations that read as though they authorised the
    decision.
    """
    for refusal in manifest.scope_refusals:
        if refusal.matches(question):
            return Finding(
                invariant_id=f"SCOPE:{refusal.label}",
                kind="scope",
                severity=severity,
                message=(
                    f"refused before retrieval ({refusal.label}): this is "
                    f"{refusal.authority}'s decision. No document makes it answerable, so "
                    f"nothing was retrieved"
                ),
            )
    return None


# --------------------------------------------------------------- derivation --

_EQUATION = re.compile(
    r"(-?\d[\d,]*(?:\.\d+)?)\s*([/*x×+-])\s*(-?\d[\d,]*(?:\.\d+)?)\s*=\s*(-?\d[\d,]*(?:\.\d+)?)"
)


def _number(token: str) -> float:
    return float(token.replace(",", ""))


def _as_number(value: Any) -> Optional[float]:
    """The value as a float, or None when it genuinely is not a number.

    Explicit rather than ``try: float(...) except``: the caller has to be able to
    ACT on "not a number" — a band it cannot evaluate must report that, not return
    silently. A numeric string ("1.4", "1,200") is still a number; True/False are
    not, because ``float(True)`` is 1.0 and a boolean is never a magnitude.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if re.fullmatch(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", text):
        return float(text)
    return None


def check_arithmetic(text: str, tolerance: float = 0.01) -> Optional[Tuple[str, float, float]]:
    """Find a stated ``a op b = c`` whose result is wrong.

    Live: "L/20 = 4800/20 = **200 mm**" -- rule right, span right, result wrong.
    The hardest defect to see by reading and trivial to catch by evaluating.
    """
    for match in _EQUATION.finditer(text or ""):
        left, op, right, stated = match.groups()
        try:
            a, b, c = _number(left), _number(right), _number(stated)
        except ValueError:
            continue
        if op == "/":
            if b == 0:
                continue
            expected = a / b
        elif op in ("*", "x", "×"):
            expected = a * b
        elif op == "+":
            expected = a + b
        else:
            expected = a - b
        if expected == 0:
            if abs(c) > tolerance:
                return match.group(0), expected, c
            continue
        if abs(expected - c) / abs(expected) > tolerance:
            return match.group(0), expected, c
    return None


def eval_derivation(
    inv: Invariant,
    figure: Figure,
    manifest: Manifest,
    siblings: Sequence[Figure] = (),
    state: Optional[Dict[str, Any]] = None,
) -> Optional[Finding]:
    """Do the stated working and the stated result agree -- and does the answer
    agree with itself? Plus the ``block_if`` conditions, ``requires_steps`` and
    the ``requires_state`` preconditions the domain sheets put on this kind.
    """
    blocked = state_precondition(inv, figure, state)
    if blocked is not None:
        return blocked

    fired = [c for c in inv.block_if if c in figure.conditions]
    if fired:
        return _finding(inv, figure, f"blocking condition: {', '.join(fired)}", fired)

    named = [d for d in figure.derivations if d in inv.forbid]
    if named:
        return _finding(inv, figure, f"forbidden derivation: {', '.join(named)}", named)

    if inv.requires_steps:
        missing = [s for s in inv.requires_steps if s not in figure.steps]
        if missing:
            return _finding(
                inv, figure,
                "calculation shown without " + ", ".join(missing)
                + " — a bare answer cannot be checked", missing,
            )

    if inv.requires:
        missing = figure.missing(inv.requires)
        if missing:
            return _finding(inv, figure, f"without {', '.join(missing)}", missing)

    wrong = check_arithmetic(figure.text)
    if wrong:
        shown, expected, stated = wrong
        return _finding(
            inv, figure,
            f"stated working and stated result disagree: '{shown}' — {expected:g}, not "
            f"{stated:g}",
        )

    for other in siblings:
        if other is figure or other.quantity != figure.quantity:
            continue
        if other.value is None or figure.value is None:
            continue
        if other.unit == figure.unit and other.value != figure.value:
            return _finding(
                inv, figure,
                f"the answer contradicts itself on {figure.quantity}: {figure.value} and "
                f"{other.value} {figure.unit or ''}".strip(),
            )
    return None


# --------------------------------------------------------------------- band --

def eval_band(inv: Invariant, figure: Figure, manifest: Manifest) -> Optional[Finding]:
    """Two meanings, both declared in the manifest and both real.

    ``{min: <number>, max: <number>}`` is a POSSIBILITY band: is the value
    physically possible? Live: a slab calculator returned ``0.2 mm`` with status
    success because metres were bound to a millimetre parameter.

    ``{min: present, max: present, same_source: true}`` is a TWO-SIDEDNESS band:
    the figure must be returned as a band at all. A single-sided lay tension is
    not a conservative answer, it is an unusable one -- and ``same_source`` means
    both bounds come from ONE analysis, not one from each.
    """
    low, high = inv.band.get("min"), inv.band.get("max")

    if str(low) == "present" or str(high) == "present":
        bounds = figure.bounds or {}
        missing = [
            name for name, wanted in (("min", low), ("max", high))
            if str(wanted) == "present" and bounds.get(name) is None
        ]
        if missing:
            return _finding(
                inv, figure,
                f"{figure.quantity} is a band — {', '.join(missing)} missing; a "
                f"single-sided figure is not a conservative answer, it is an unusable one",
                missing,
            )
        if inv.band.get("same_source"):
            if bounds.get("source_id_min") != bounds.get("source_id_max"):
                return _finding(
                    inv, figure,
                    f"the two bounds of {figure.quantity} come from different sources — a "
                    f"band assembled from two analyses is not a band", ["same_source"],
                )
        return None

    if figure.value is None or isinstance(figure.value, bool):
        return None
    value = _as_number(figure.value)
    if value is None:
        # A band that could not be evaluated is NOT a pass. This used to `try:
        # float(...) except: return None`, so a figure carrying a non-numeric value
        # sailed through the one check that exists to catch an impossible magnitude
        # -- a skipped check reported as a pass, which is the defect this whole
        # layer exists to prevent. The repo's CI guard caught it.
        return _finding(
            inv, figure,
            f"{figure.quantity} is governed by a possible-range band but its value "
            f"{figure.value!r} is not a number, so the range could not be checked — "
            f"an unchecked band is not a pass",
        )
    if low is not None and value < float(low):
        return _finding(
            inv, figure,
            f"{figure.quantity} = {figure.value}{figure.unit or ''} is below the possible "
            f"minimum {low}{figure.unit or ''} — check the unit it was computed in",
        )
    if high is not None and value > float(high):
        return _finding(
            inv, figure,
            f"{figure.quantity} = {figure.value}{figure.unit or ''} is above the possible "
            f"maximum {high}{figure.unit or ''} — check the unit it was computed in",
        )
    return None
