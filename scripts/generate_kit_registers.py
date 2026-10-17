#!/usr/bin/env python3
"""Give every kit the figure register the six original kits already had.

Six kits were built with a ``design_basis.yaml`` (``operating_basis`` for
og_operations): the domain's own figure names, each entry carrying the qualifiers
that figure is meaningless without, and the file declaring its own scope. Eleven
were built later as declarations only, and got a generated per-quantity
``figures:`` block in the manifest instead -- a coarser register that could not say
"this value is meaningless without its train and its averaging basis".

This writes the register for the eleven, and removes the manifest ``figures:``
block once it has, so that across all seventeen kits there is ONE figure register
and it is always ``design_basis.yaml``. That uniformity is the point: the shared
loader (``kit_engine.interview.load_design_basis``) already reads it, so no kit
needs a bespoke loader -- which is what ``TrackBasis`` and its five siblings were
doing before today.

NOTHING HERE IS INVENTED. Every part of an entry is derived from what the kit
already declares:

  the figures        the figure-bearing quantities, by the same rule
                     add_figure_questions.py uses -- a quantity whose only rules
                     are `currency` ones is a record whose staleness is tracked,
                     not a value anybody supplies
  the units          the quantity's own declared units
  the qualifiers     the fields this kit's OWN `qualifier` invariants demand for
                     that quantity, so a filled entry cannot then be refused for
                     incompleteness
  the answer fields  the per-domain fields from the owner sheet's "Answer format:"
                     line, which is where `plant`, `train`, `quality_band` and
                     `code_edition` come from
  scope and source   the manifest's `scope` and the sheet's own source document

EVERY VALUE IS NULL, and stays null until an interview fills it. A null value is
legal and is not a stub: the figure has no value, so anything needing it refuses
and names the question. A MISSING QUALIFIER is a different thing -- the register
declares the keys so that a half-qualified figure is visible as such.

An existing register is NEVER overwritten. The six that have one are the record.

    python scripts/generate_kit_registers.py          # write
    python scripts/generate_kit_registers.py --check  # report, write nothing
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
from typing import Any, Dict, List, Tuple

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
BLOCKS = ROOT / "app" / "blocks"

#: Provenance keys every entry carries, after the domain's own qualifiers. These
#: are not domain vocabulary -- they are how any figure is attributed at all.
PROVENANCE_KEYS = ("source", "revision", "date")

#: The answer-format entry that IS the value rather than a field beside it.
VALUE_FIELD = "value"


class RegisterError(ValueError):
    """Refuse to write rather than write something derived from a guess."""


def _figure_kinds() -> Tuple[str, ...]:
    """Kinds that mean somebody has to SUPPLY this quantity."""
    return ("qualifier", "band", "unit_discipline", "grounding", "authority",
            "provenance", "derivation")


def _classes(manifest: Dict[str, Any]) -> Dict[str, Tuple[str, ...]]:
    out: Dict[str, List[str]] = {}
    for name, spec in (manifest.get("quantities") or {}).items():
        for cls in ((spec or {}).get("classes") or ()):
            out.setdefault(str(cls), []).append(str(name))
    return {k: tuple(v) for k, v in out.items()}


def _governs(record: Dict[str, Any], quantity: str,
             classes: Dict[str, Tuple[str, ...]], *, blanket: bool) -> bool:
    raw = (record.get("applies_to") or {}).get("quantity")
    names = [] if raw is None else ([raw] if isinstance(raw, str) else list(raw))
    spelled = [str(n) for n in names]
    if not spelled:
        return blanket
    if "any" in spelled:
        return blanket
    if quantity in spelled:
        return True
    return any(n.startswith("any_") and quantity in classes.get(n, ()) for n in spelled)


def is_figure(quantity: str, spec: Dict[str, Any], invariants: List[Dict[str, Any]],
              classes: Dict[str, Tuple[str, ...]], triggers: Tuple[str, ...]) -> bool:
    """Whether a person supplies this, or whether its currency is merely tracked.

    The same three-signal rule as add_figure_questions.py, and for the same reason:
    deciding on units alone skipped a PCN and a hazard classification, both
    unitless and both certainly figures; counting a blanket `quantity: any` made a
    warranty and a P&ID revision into figures, and neither is something anybody
    types in.
    """
    units = [str(u).strip() for u in ((spec or {}).get("units") or ())]
    has_unit = any(u and u not in ("—", "-") for u in units)
    if has_unit or quantity not in triggers:
        return True
    governed = {
        str(r.get("kind")) for r in invariants
        if _governs(r, quantity, classes, blanket=False)
    }
    if not governed:
        return False
    return bool(governed & set(_figure_kinds()))


def qualifiers_for(quantity: str, invariants: List[Dict[str, Any]],
                   classes: Dict[str, Tuple[str, ...]]) -> List[str]:
    """Fields this kit's own qualifier invariants demand with this figure.

    ``claim_class`` is deliberately IGNORED here, and that is a choice about what a
    register is for. A blanket record narrowed to one claim class still contributes
    its fields to every entry, because the register is the sheet an owner fills in
    before anyone knows which figures a host will label — listing a field the kit
    might demand is prudent, and omitting it would under-ask.

    THEREFORE THE REGISTER IS NOT EVIDENCE ABOUT ENFORCEMENT. A field appearing on
    all of a kit's entries does not mean every figure is required to carry it; it may
    be demanded only of one claim class. Reading it the other way is a circular
    argument — the register is generated FROM these records, so it cannot be used to
    conclude anything about them — and I made exactly that mistake on stadium_venue:
    cited its register as proof that three records should not be claim_class-gated,
    when the register only said so because this function ignored their gate. The
    owner's G2 spec stands; ask the invariants what is enforced, never the register.

    Two kits are affected today: stadium_venue (six identity fields) and heritage
    (consent_ref, evidence_basis).
    """
    wanted: List[str] = []
    for record in invariants:
        if record.get("kind") != "qualifier":
            continue
        if not _governs(record, quantity, classes, blanket=True):
            continue
        for field in (record.get("requires") or ()):
            if str(field) not in wanted:
                wanted.append(str(field))
    return wanted


def answer_fields(kit: str) -> List[str]:
    """The per-domain fields from the owner sheet's 'Answer format:' line."""
    path = BLOCKS / kit / "questions.yaml"
    if not path.is_file():
        return []
    sheet = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for entry in (sheet.get("answer_format") or ()):
        key = str(entry).strip().lower().replace(" ", "_")
        if key in (VALUE_FIELD, "unit"):
            continue
        # "building / system" and "agent / item" are one axis written as a pair;
        # keep both halves, each is a real key the domain uses.
        for half in re.split(r"\s*/\s*", key):
            half = half.strip("_")
            if half and half not in out:
                out.append(half)
    return out


#: Answer-format entries that describe HOW a figure is attributed rather than WHICH
#: asset it belongs to. Everything else on that line is an identity axis.
_NOT_IDENTITY = frozenset({
    "value", "unit", "source", "date", "revision", "source_document",
    "confirmed_or_indicative", "protocol_version", "code_edition", "basis",
    "contract_or_manual_reference",
})


def identity_axes(kit: str) -> List[str]:
    """The axes that make a figure THIS asset's figure and nobody else's.

    Read off the owner sheet's own "Answer format:" line. This is not a guess: for
    the four kits that have both a sheet and a hand-written register, the derived
    axes reproduce the hand-written scope exactly -- "plant / train" gives
    "plant- and train-specific", "route / line" gives "route- and line-specific",
    and likewise for og_operations and fire_protection.
    """
    path = BLOCKS / kit / "questions.yaml"
    if not path.is_file():
        return []
    sheet = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    axes: List[str] = []
    for entry in (sheet.get("answer_format") or ()):
        for half in re.split(r"\s*/\s*", str(entry).strip().lower()):
            half = half.strip()
            if half and half.replace(" ", "_") not in _NOT_IDENTITY and half not in axes:
                axes.append(half)
    return axes


def _scope_from_axes(kit: str) -> str:
    axes = identity_axes(kit)
    if not axes:
        return ""
    # An axis written as a choice ("adult or paediatric") is a CATEGORY the figure
    # carries, not a place it belongs to; it stays an entry key but would make this
    # sentence say "never carry to another adult or paediatric". Scope names the
    # places.
    places = [a for a in axes if " or " not in a]
    if not places:
        return ""
    # House style, as the six hand-written registers phrase it:
    # "plant- and train-specific — never carry to another plant or train".
    if len(places) == 1:
        named, targets = f"{places[0]}-specific", places[0]
    else:
        named = "-, ".join(places[:-1]) + f"- and {places[-1]}-specific"
        targets = ", ".join(places[:-1]) + f" or {places[-1]}"
    return f"{named} — never carry a figure to another {targets}"


def build(kit: str) -> Tuple[str, Dict[str, Any]]:
    manifest = yaml.safe_load((BLOCKS / kit / "manifest.yaml").read_text(encoding="utf-8")) or {}
    records = yaml.safe_load((BLOCKS / kit / "invariants.yaml").read_text(encoding="utf-8")) or {}
    invariants = list(records.get("invariants") or [])
    if not invariants:
        raise RegisterError(f"{kit}: no invariants; refusing to derive a register")

    classes = _classes(manifest)
    triggers = tuple(str(k) for k in (manifest.get("staleness_triggers") or {}))
    fields = answer_fields(kit)
    scope = str(manifest.get("scope") or "").strip() or _scope_from_axes(kit)
    if not scope:
        raise RegisterError(
            f"{kit}: no scope in the manifest and none derivable from the sheet's "
            f"answer format. A register whose scope is not stated invites a figure "
            f"being carried where it does not apply, which is the thing every one of "
            f"these files warns about in its own header")

    sheet_path = BLOCKS / kit / "questions.yaml"
    sheet = yaml.safe_load(sheet_path.read_text(encoding="utf-8")) or {} \
        if sheet_path.is_file() else {}

    entries: Dict[str, Any] = {}
    for name, spec in sorted((manifest.get("quantities") or {}).items()):
        name = str(name)
        if not is_figure(name, spec or {}, invariants, classes, triggers):
            continue
        units = [str(u) for u in ((spec or {}).get("units") or ())]
        entry: Dict[str, Any] = {"value": None, "unit": units[0] if units else None}
        for key in qualifiers_for(name, invariants, classes):
            entry[key] = None
        for key in fields:
            entry.setdefault(key, None)
        for key in PROVENANCE_KEYS:
            entry.setdefault(key, None)
        entries[name] = entry

    if not entries:
        raise RegisterError(f"{kit}: derived no figures; refusing to write an empty register")

    source = str(sheet.get("source_document") or "") or f"{kit} kit declaration"
    return _render(kit, scope, source, sheet, entries), entries


def _render(kit: str, scope: str, source: str, sheet: Dict[str, Any],
            entries: Dict[str, Any]) -> str:
    title = str(sheet.get("title") or "").strip()
    out: List[str] = [
        f"# {kit} reasoning layer — figure register.",
        "#",
        f"# Source of truth: {title or f'the {kit} kit declaration'}.",
        "# NO INTERVIEW HAS RUN. Every `value` below is null on purpose and stays null",
        "# until an interview fills it; see KNOWN_GAPS.md.",
        "#",
        "# A null value is LEGAL and is not a stub: the figure has no value, so anything",
        "# needing it refuses and names the question. A MISSING QUALIFIER is a different",
        "# thing — the keys below are the ones this kit's own `qualifier` invariants",
        "# demand, so a half-qualified figure is visible as half-qualified rather than",
        "# passing as a figure. A half-qualified figure is how one asset's limit ends up",
        "# answering another's question.",
        "#",
        "# GENERATED by scripts/generate_kit_registers.py from this kit's own manifest,",
        "# invariants and question sheet. Once an interview fills a value, this file is",
        "# the record and the generator will not touch it again.",
        f"source: {_scalar(source)}",
        f"scope: {_scalar(scope)}",
        "interview_status: 'not run — every value is null (KNOWN_GAPS.md)'",
        "",
        "design_basis:",
    ]
    for name, entry in entries.items():
        out.append(f"  {name}:")
        for key, value in entry.items():
            out.append(f"    {key}: {_scalar(value) if isinstance(value, str) else 'null'}")
    return "\n".join(out) + "\n"


def _scalar(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def strip_figures_block(kit: str) -> bool:
    """Remove the generated manifest figures block once the register exists.

    One register per kit, and it is design_basis.yaml. Leaving both would be the
    same fact in two places, free to disagree — and it is what put nine null
    figures over datacentre's answered register in the first place.
    """
    path = BLOCKS / kit / "manifest.yaml"
    text = path.read_text(encoding="utf-8")
    before = yaml.safe_load(text) or {}
    if not before.get("figures"):
        return False
    out = re.sub(r"\n# The questions this kit needs answered.*\Z", "", text, flags=re.S)
    out = re.sub(r"\nfigures:\n(?:[ \t].*\n?|\n)*\Z", "\n", out)
    reloaded = yaml.safe_load(out) or {}
    if reloaded.get("figures"):
        raise RegisterError(f"{kit}: the figures block survived the strip")
    if set(reloaded) != set(before) - {"figures"}:
        raise RegisterError(
            f"{kit}: stripping the figures block changed other keys: "
            f"{sorted(set(before) ^ set(reloaded))}")
    for key in reloaded:
        if reloaded[key] != before[key]:
            raise RegisterError(f"{kit}: stripping changed '{key}'")
    path.write_text(out.rstrip("\n") + "\n", encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    kits = sorted(p.parent.name for p in BLOCKS.glob("*/manifest.yaml")
                  if (p.parent / "invariants.yaml").is_file())
    wrote = kept = 0
    for kit in kits:
        register = BLOCKS / kit / "design_basis.yaml"
        if register.is_file():
            kept += 1
            print(f"  {kit:22} HAS a register already — untouched")
            continue
        text, entries = build(kit)
        # Parse what we would write, whether or not we write it: a --check that
        # does less than the write path reports green over output that cannot load.
        try:
            back = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise RegisterError(f"{kit}: rendered register does not parse: {exc}") from exc
        if len(back.get("design_basis") or {}) != len(entries):
            raise RegisterError(f"{kit}: rendered {len(entries)} figures, reloads "
                                f"{len(back.get('design_basis') or {})}")
        filled = [n for n, e in (back.get("design_basis") or {}).items()
                  if (e or {}).get("value") is not None]
        if filled:
            raise RegisterError(f"{kit}: a value got filled, which this must never do: {filled}")
        if not args.check:
            register.write_text(text, encoding="utf-8")
            strip_figures_block(kit)
        wrote += 1
        quals = max((len(e) - 1 for e in entries.values()), default=0)
        print(f"  {kit:22} {len(entries):3} figure(s), up to {quals} qualifier key(s)")

    print(f"\n{wrote} register(s) {'would be ' if args.check else ''}written | "
          f"{kept} already had one")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RegisterError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
