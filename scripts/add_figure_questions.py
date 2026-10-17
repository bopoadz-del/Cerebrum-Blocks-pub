#!/usr/bin/env python3
"""Give every kit a machine-readable list of the questions it needs answered.

The kits declare their vocabulary and their rules. What they did NOT declare is
the list of figures the domain has to supply and the question that fills each one
-- those existed only as prose in KNOWN_GAPS.md, which nothing can read. So the
Floor LLM had nothing to ask from, and the platform had nothing to collect.

This writes a ``figures:`` block into each manifest: one entry per figure-bearing
quantity, ``value: null``, and a ``question`` that says what is being asked AND
which qualifiers must arrive with the answer.

The question is DERIVED, not invented:

  * the subject is the quantity the kit already declares
  * the required qualifiers come from the kit's own ``qualifier`` invariants for
    that quantity -- so the question asks for exactly what the rules will demand,
    and an answer that satisfies the question cannot then be refused for
    incompleteness
  * the units come from the quantity's own declared units
  * the scope comes from the kit's own ``scope`` line

Unitless "artifact" quantities (a P&ID revision, a warranty, a condition survey)
are NOT questions -- they are records whose currency is tracked, not figures
someone types in. They are skipped, and the script says how many.

Nothing here fills a value. Every entry is null, which is the point: the platform
refuses anything needing it and names this question.

    python scripts/add_figure_questions.py          # write
    python scripts/add_figure_questions.py --check  # report, write nothing
"""
from __future__ import annotations

import argparse
import pathlib
import re
from typing import Any, Dict, List, Tuple

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
BLOCKS = ROOT / "app" / "blocks"

#: FIGURE-GATING kinds. If any of these governs a quantity, the kit has rules
#: about STATING it, so somebody has to supply it and it is a question.
FIGURE_KINDS = ("qualifier", "band", "unit_discipline", "grounding", "authority",
                "provenance", "derivation")


def is_artifact(quantity: str, invariants: List[Dict[str, Any]],
                classes: Dict[str, Tuple[str, ...]],
                spec: Dict[str, Any] = None,
                trigger_keys: Tuple[str, ...] = ()) -> bool:
    """An artifact is a record whose CURRENCY the kit tracks, not a figure a person
    supplies -- a P&ID revision, a warranty, a condition survey.

    Deciding this on units was wrong and over-skipped real questions: a PCN and a
    hazard classification are both unitless and both absolutely are questions. The
    honest discriminator comes from the kit itself -- if the only rules about a
    quantity are `currency` ones, nothing ever asks anyone to state it; it is
    tracked, not answered. If ANY figure-gating rule governs it, it is a question.
    """
    # THREE signals, and all three must agree, because no one of them works
    # alone. Attempt 1 used units: it skipped a PCN and a hazard classification,
    # which are unitless and are certainly questions. Attempt 2 used invariant
    # coverage: a blanket `quantity: any` governs everything, so nothing looked
    # like an artifact. Attempt 3 used explicit naming only: the kits do not name
    # every quantity, so a crane SWL and a stinger radius -- plain figures --
    # dropped out. An artifact is a quantity that (a) exists as a staleness
    # trigger KEY, which is the only reason the plumbing ones were declared at
    # all, AND (b) carries no real unit, AND (c) is named by no figure-gating
    # rule. Anything else is something a person has to supply.
    units = [str(u).strip() for u in ((spec or {}).get("units") or ())]
    has_real_unit = any(u and u not in ("—", "-") for u in units)
    if has_real_unit or quantity not in trigger_keys:
        return False

    governed_by = set()
    for record in invariants:
        raw = (record.get("applies_to") or {}).get("quantity")
        names = [] if raw is None else ([raw] if isinstance(raw, str) else list(raw))
        spelled = [str(n) for n in names]
        # A blanket `quantity: any` governs EVERYTHING, so it distinguishes
        # nothing and must not make an artifact look like a question. Only an
        # EXPLICIT naming counts here -- by name, or by a class the quantity
        # declares itself a member of. (First cut used units, which skipped a PCN
        # and a hazard classification; second cut counted `any`, which made a
        # warranty and a P&ID revision into questions. Neither is a figure anyone
        # types in, and both are unitless. Explicit naming is the signal.)
        governs = (
            quantity in spelled
            or any(n.startswith("any_") and quantity in classes.get(n, ()) for n in spelled)
        )
        if governs:
            governed_by.add(str(record.get("kind")))
    if not governed_by:
        return True
    return not (governed_by & set(FIGURE_KINDS))


def required_qualifiers(quantity: str, invariants: List[Dict[str, Any]],
                        classes: Dict[str, Tuple[str, ...]]) -> List[str]:
    """Which qualifiers the kit's OWN rules will demand with this figure."""
    wanted: List[str] = []
    for record in invariants:
        if record.get("kind") != "qualifier":
            continue
        raw = (record.get("applies_to") or {}).get("quantity")
        names = [] if raw is None else ([raw] if isinstance(raw, str) else list(raw))
        governs = (
            not names
            or "any" in [str(n) for n in names]
            or quantity in [str(n) for n in names]
            or any(str(n).startswith("any_") and quantity in classes.get(str(n), ())
                   for n in names)
        )
        if not governs:
            continue
        for field in (record.get("requires") or ()):
            if str(field) not in wanted:
                wanted.append(str(field))
    return wanted


def question_for(quantity: str, spec: Dict[str, Any], qualifiers: List[str],
                 scope: str) -> str:
    subject = quantity.replace("_", " ")
    units = [str(u) for u in ((spec or {}).get("units") or ())]
    unit_part = f" in {' or '.join(units)}" if units else ""
    scope_part = f" for this {scope}" if scope else ""
    text = f"What is the {subject}{unit_part}{scope_part}?"
    if qualifiers:
        text += (
            " The answer must arrive with "
            + ", ".join(qualifiers)
            + " — without those it cannot be acted on and will be refused."
        )
    text += " Leave unanswered rather than estimating: an unanswered figure refuses, an estimate ships."
    return text


def scope_word(manifest: Dict[str, Any], kit: str) -> str:
    raw = str(manifest.get("scope") or "")
    match = re.match(r"([a-z\- ]+?)-specific", raw)
    if match:
        return match.group(1).strip()
    for word in ("site", "plant", "station", "building", "terminal", "airport",
                 "practice", "clinic", "facility", "vessel", "route", "operator",
                 "project"):
        if word in raw.lower() or word in kit:
            return word
    return "platform"


def build_block(kit: str) -> Tuple[Dict[str, Any], int, int]:
    manifest = yaml.safe_load((BLOCKS / kit / "manifest.yaml").read_text(encoding="utf-8")) or {}
    records = yaml.safe_load((BLOCKS / kit / "invariants.yaml").read_text(encoding="utf-8")) or {}
    invariants = list(records.get("invariants") or [])

    classes: Dict[str, List[str]] = {}
    for name, spec in (manifest.get("quantities") or {}).items():
        for cls in ((spec or {}).get("classes") or ()):
            classes.setdefault(str(cls), []).append(str(name))
    classes_t = {k: tuple(v) for k, v in classes.items()}

    trigger_keys = tuple(str(k) for k in (manifest.get("staleness_triggers") or {}))
    scope = scope_word(manifest, kit)
    figures: Dict[str, Any] = {}
    skipped = 0
    for name, spec in sorted((manifest.get("quantities") or {}).items()):
        if is_artifact(str(name), invariants, classes_t, spec or {}, trigger_keys):
            skipped += 1
            continue
        qualifiers = required_qualifiers(str(name), invariants, classes_t)
        figures[str(name)] = {
            "value": None,
            "unit": (list((spec or {}).get("units") or []) or [None])[0],
            "question": question_for(str(name), spec or {}, qualifiers, scope),
            "requires": qualifiers,
            "answered_by": None,
            "answered_at": None,
            "source": None,
        }
    return figures, len(figures), skipped


def write_block(kit: str, figures: Dict[str, Any]) -> None:
    """Append the block as text, so the manifest keeps its comments and order."""
    path = BLOCKS / kit / "manifest.yaml"
    text = path.read_text(encoding="utf-8").rstrip("\n")
    # Replace an existing block rather than appending a second one.
    text = re.sub(r"\n# The questions this kit needs answered.*\Z", "", text, flags=re.S)
    text = re.sub(r"\nfigures:\n(?:[ \t].*\n?|\n)*\Z", "\n", text)
    # Strip AGAIN after removing the block. The first rstrip ran before the block
    # was cut, so the blank lines that preceded it survived and a fresh separator
    # was added on top of them -- one more blank line in every kit on every run, in
    # a script whose docstring says it is idempotent. A generator that churns its
    # output makes every re-run a diff nobody can review.
    text = text.rstrip("\n")

    lines = [
        "",
        "# The questions this kit needs answered, and nothing else. Every value is",
        "# null and stays null until someone answers: the owner during the build, or",
        "# the operator later through /v1/reasoning/pending. An unanswered figure is",
        "# NOT a stub -- the platform refuses anything needing it and names the",
        "# question, so there is no plausible number to mistake for a real one. An",
        "# answer is recorded with answered_by, answered_at and source, because an",
        "# unattributed figure is not evidence whoever supplied it.",
        "#",
        "# `requires` is derived from this kit's own qualifier invariants, so an answer",
        "# that satisfies the question cannot then be refused for incompleteness.",
        "figures:",
    ]
    for name, entry in figures.items():
        lines.append(f"  {name}:")
        lines.append("    value: null")
        unit = entry["unit"]
        lines.append(f"    unit: {unit if unit else 'null'}")
        question = entry["question"].replace('"', "'")
        lines.append(f"    question: >-")
        for chunk in _wrap(question, "      "):
            lines.append(chunk)
        req = entry["requires"]
        lines.append(f"    requires: [{', '.join(req)}]" if req else "    requires: []")
        lines.append("    answered_by: null")
        lines.append("    answered_at: null")
        lines.append("    source: null")
    path.write_text(text + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def _wrap(text: str, indent: str, width: int = 84) -> List[str]:
    out, line = [], indent
    for word in text.split():
        if len(line) + len(word) + 1 > width and line.strip():
            out.append(line.rstrip())
            line = f"{indent}{word} "
        else:
            line += word + " "
    if line.strip():
        out.append(line.rstrip())
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    kits = sorted(p.parent.name for p in BLOCKS.glob("*/manifest.yaml")
                  if (p.parent / "invariants.yaml").is_file())

    # A kit that already has a design_basis.yaml HAS a figure register, and a
    # better one: the figure names are the domain's own, each entry carries the
    # qualifiers that figure is meaningless without, and the file declares its own
    # scope. Generating a second register beside it produced one that was coarser
    # and unanswerable -- and on the one kit whose register was FILLED IN it wrote
    # 9 null figures over a facility that had answered 17 of 18, so the kit
    # reported an answered domain as an empty one. The file was in the same
    # directory the whole time and this script never read it.
    with_register = sorted(
        kit for kit in kits if (BLOCKS / kit / "design_basis.yaml").is_file())
    kits = [kit for kit in kits if kit not in with_register]

    total_q = total_skipped = 0
    for kit in kits:
        figures, count, skipped = build_block(kit)
        total_q += count
        total_skipped += skipped
        if not args.check:
            write_block(kit, figures)
            reloaded = yaml.safe_load((BLOCKS / kit / "manifest.yaml")
                                      .read_text(encoding="utf-8")) or {}
            got = reloaded.get("figures") or {}
            if len(got) != count:
                raise SystemExit(f"{kit}: wrote {count} figures, manifest reloads {len(got)}")
            unfilled = [n for n, e in got.items() if (e or {}).get("value") is not None]
            if unfilled:
                raise SystemExit(f"{kit}: a value got filled, which this must never do: {unfilled}")
        print(f"  {kit:22} {count:3} question(s) | {skipped:2} artifact quantit(ies) skipped")
    print(f"{len(kits)} kits | {total_q} questions | {total_skipped} artifacts skipped")
    if with_register:
        print("\nSKIPPED — these kits already have design_basis.yaml, which IS their")
        print("figure register. Fill that file; nothing is generated beside it:")
        for kit in with_register:
            print(f"  {kit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
