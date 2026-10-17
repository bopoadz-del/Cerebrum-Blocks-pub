#!/usr/bin/env python3
"""Turn the domain owner's own question sheets into each kit's interview.

The kits already declared their vocabulary and their rules. What they could not
invent is the question sheet: the actual list of things a domain has to supply,
in the owner's own words, with the owner's own [GATE] / [GAP] mark on each.
Those sheets live verbatim in ``docs/kit_questions/<kit>.md``; this script is the
ONE place their shape is interpreted, and it writes ``app/blocks/<kit>/questions.yaml``.

Why a parser and not 1,200 hand-written YAML records: the sheet is the record of
what was asked for. If the YAML were authored by hand it would be a second copy
of the same fact, free to drift from the sheet, and nothing would catch it. Edit
the markdown and re-run; never hand-edit the YAML.

What the sheet carries that the derived questions could not:

  [GATE] / [GAP]   the owner's own split. A GATE question blocks — the platform
                   refuses anything needing it. A GAP question is experience the
                   platform is better for having and is not blocked without.
  answer format    the per-domain fields every answer must arrive with. Fit-out
                   wants quality band and market; fire protection wants code
                   edition; dental wants adult-or-paediatric and protocol version.
  the real subject "your rate per package — partitions, ceilings, raised floor,
                   ..." instead of the derived "what is the rate?", which was one
                   number for a whole domain and unanswerable in practice.

An UNMARKED question (the FM sheet marks none) is treated as GATING, not as a
GAP. A question whose class we cannot read must block rather than pass: that is
the same fail-closed rule the rest of this layer runs on, and it is recorded here
as ``gate: null`` so a reader can see it was unmarked rather than marked GATE.

NOTHING in this file stores an answer. Answers are per-platform and per-client
and live in the platform's own storage; the kit is a signed Store block shared by
every customer, and one client's figures arriving inside another's kit is exactly
the provenance failure this layer exists to prevent.

    python scripts/import_kit_questions.py          # write
    python scripts/import_kit_questions.py --check  # report, write nothing
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHEETS = ROOT / "docs" / "kit_questions"
BLOCKS = ROOT / "app" / "blocks"

#: `B — Rates`, `Section 1 — The asset register`, `1 — Hazard classification`,
#: `Section A — Figures that must never be guessed`. The em-dash is the sheet's
#: own separator throughout; a hyphen here would silently match prose.
SECTION_RE = re.compile(r"^(?:Section\s+)?([A-Z]|\d{1,2})\s+—\s+(.+?)\s*$")

#: `· B.1 [GATE] text`, `· 9.3.1 [GATE] text`, `· Do you hold it? ...` (no id, no
#: mark). The id must contain a dot, or `Do` in the last example parses AS an id.
BULLET_RE = re.compile(
    r"^·\s*"
    r"(?:(?P<id>[A-Za-z]{1,2}\.\d+(?:\.\d+)*|\d{1,2}\.\d+(?:\.\d+)*)\s+)?"
    r"(?:\[(?P<mark>GATE|GAP)\]\s*)?"
    r"(?P<text>\S.*?)\s*$"
)

#: `1. A statutory item found overdue, ...` — the FM and "five questions" lists.
NUMBERED_RE = re.compile(r"^(?P<n>\d{1,2})\.\s+(?P<text>\S.*?)\s*$")

ANSWER_FORMAT_RE = re.compile(r"^Answer format:\s*(.+?)\s*$")


class SheetError(ValueError):
    """The sheet cannot be read. Nothing is written — a half-imported interview
    would look like a complete one."""


def _scalar(value: str) -> str:
    """One YAML scalar, single-quoted.

    Not ``yaml.safe_dump``: dumping a bare scalar emits a whole YAML *document*,
    and for a long string that document ends with a ``...`` marker which lands in
    the middle of the mapping and makes the file unparseable. The first cut used
    safe_dump and --check reported all 15 kits green, because --check never
    reloaded what it would have written.
    """
    return "'" + str(value).replace("'", "''") + "'"


def _covers(text: str, quantities: Dict[str, Any]) -> List[str]:
    """Which declared quantities this question is visibly about.

    Exact naming only — the quantity's own name with underscores or spaces, or
    one of its declared aliases as a whole word. A fuzzy match here would put a
    question against a figure it does not actually answer, and the platform
    would then report a figure as asked when nothing asks it.
    """
    hay = text.lower()
    found: List[str] = []
    for name, spec in quantities.items():
        spec = spec or {}
        needles = [str(name).replace("_", " "), str(name)]
        needles += [str(a) for a in (spec.get("aliases") or ())]
        for needle in needles:
            token = needle.lower().strip()
            if not token:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", hay):
                found.append(str(name))
                break
    return sorted(set(found))


def parse_sheet(path: pathlib.Path) -> Tuple[str, List[str], Dict[str, Any], List[Dict[str, Any]]]:
    """(title, answer_format, sections, questions). Strict: an unreadable line in
    a sheet raises rather than being dropped, because a dropped GATE question is
    a gate that silently is not there."""
    title = ""
    answer_format: List[str] = []
    sections: Dict[str, Any] = {}
    questions: List[Dict[str, Any]] = []
    section_id: Optional[str] = None
    preamble: Dict[str, List[str]] = {}
    counts: Dict[str, int] = {}

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("# "):
            title = line[2:].strip()
            continue
        fmt = ANSWER_FORMAT_RE.match(line)
        if fmt:
            answer_format = [p.strip() for p in fmt.group(1).split("·") if p.strip()]
            continue
        sec = SECTION_RE.match(line)
        if sec and not line.startswith("·"):
            section_id = sec.group(1)
            if section_id in sections:
                raise SheetError(f"{path.name}:{lineno}: section '{section_id}' declared twice")
            sections[section_id] = {"title": sec.group(2), "preamble": None}
            preamble[section_id] = []
            counts[section_id] = 0
            continue
        if section_id is None:
            # Prose before the first section header is the sheet's own preamble;
            # there is none in any sheet, so treat it as an error rather than
            # discarding text nobody will notice is gone.
            raise SheetError(f"{path.name}:{lineno}: text before the first section: {line!r}")

        bullet = BULLET_RE.match(line)
        if bullet:
            counts[section_id] += 1
            qid = bullet.group("id")
            assigned = qid is None
            if assigned:
                qid = f"{section_id}.q{counts[section_id]}"
            mark = bullet.group("mark")
            questions.append({
                "id": qid,
                "section": section_id,
                "gate": None if mark is None else (mark == "GATE"),
                "id_assigned": assigned,
                "text": bullet.group("text"),
            })
            continue
        num = NUMBERED_RE.match(line)
        if num:
            counts[section_id] += 1
            questions.append({
                "id": f"{section_id}.{num.group('n')}",
                "section": section_id,
                "gate": None,
                "id_assigned": True,
                "text": num.group("text"),
            })
            continue
        if line.strip() in {str(n) + "." for n in range(1, 21)}:
            # A blank numbered slot ("1." on its own) in the five-questions list.
            # It is a slot to fill, not a question with text; skip it, and the
            # section's own question carries the ask.
            continue
        preamble[section_id].append(line.strip())

    for sid, lines in preamble.items():
        if lines:
            sections[sid]["preamble"] = " ".join(lines)
    # A section whose whole body is prose with no bullets IS the question (FM
    # sections 10, 11, 12). Emit it as one, rather than losing the section.
    for sid, spec in sections.items():
        if counts.get(sid, 0) == 0:
            body = spec.get("preamble")
            if not body:
                raise SheetError(
                    f"{path.name}: section '{sid}' ({spec['title']}) has no questions "
                    f"and no text — a section that asks nothing should not be in the sheet"
                )
            questions.append({
                "id": sid, "section": sid, "gate": None, "id_assigned": True,
                "text": body,
            })
    if not questions:
        raise SheetError(f"{path.name}: no questions found")
    if not answer_format:
        raise SheetError(
            f"{path.name}: no 'Answer format:' line — without it the platform does not "
            f"know which fields an answer must arrive with"
        )
    return title, answer_format, sections, questions


def render(kit: str, sheet: pathlib.Path, title: str, answer_format: List[str],
           sections: Dict[str, Any], questions: List[Dict[str, Any]]) -> str:
    rel = sheet.relative_to(ROOT).as_posix()
    out: List[str] = [
        f"# GENERATED from {rel} by scripts/import_kit_questions.py — do not hand-edit.",
        "# Edit the markdown sheet and re-run. The sheet is the record of what the domain",
        "# owner actually asked for; this file is only its machine-readable form.",
        "#",
        "# gate: true  -> [GATE]. The platform refuses anything needing it until answered.",
        "# gate: false -> [GAP].  Experience worth having; does not block.",
        "# gate: null  -> the sheet marked neither. Treated as GATING, because a question",
        "#                whose class cannot be read must block rather than pass.",
        "#",
        "# There is deliberately NO answer slot in this file. Answers are per-platform and",
        "# per-client; this kit is a signed Store block shared by every customer.",
        f"kit: {kit}",
        f"source_document: {rel}",
        f"title: {_scalar(title)}",
        "answer_format:",
    ]
    for fieldname in answer_format:
        out.append(f"  - {_scalar(fieldname)}")
    out.append("sections:")
    for sid, spec in sections.items():
        out.append(f"  {_scalar(sid)}:")
        out.append(f"    title: {_scalar(spec['title'])}")
        if spec.get("preamble"):
            out.append("    preamble: >-")
            out.extend(_wrap(spec["preamble"], "      "))
    out.append("questions:")
    for q in questions:
        out.append(f"  - id: {_scalar(q['id'])}")
        out.append(f"    section: {_scalar(q['section'])}")
        out.append(f"    gate: {'null' if q['gate'] is None else str(q['gate']).lower()}")
        if q["id_assigned"]:
            out.append("    id_assigned: true   # the sheet gave no id; this one is positional")
        if q["covers"]:
            out.append(f"    covers: [{', '.join(q['covers'])}]")
        out.append("    text: >-")
        out.extend(_wrap(q["text"], "      "))
    return "\n".join(out) + "\n"


def _wrap(text: str, indent: str, width: int = 92) -> List[str]:
    out: List[str] = []
    line = indent
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
    total_gate = total_gap = total_unmarked = 0
    without_sheet: List[str] = []

    for kit in kits:
        sheet = SHEETS / f"{kit}.md"
        if not sheet.is_file():
            without_sheet.append(kit)
            continue
        manifest = yaml.safe_load((BLOCKS / kit / "manifest.yaml").read_text(encoding="utf-8")) or {}
        quantities = manifest.get("quantities") or {}
        title, answer_format, sections, questions = parse_sheet(sheet)

        seen: Dict[str, int] = {}
        for q in questions:
            q["covers"] = _covers(q["text"], quantities)
            seen[q["id"]] = seen.get(q["id"], 0) + 1
        dupes = sorted(qid for qid, n in seen.items() if n > 1)
        if dupes:
            raise SheetError(
                f"{sheet.name}: duplicate question id(s) {', '.join(dupes)} — an id is how "
                f"an answer finds its question, so two questions cannot share one"
            )

        gate = sum(1 for q in questions if q["gate"] is True)
        gap = sum(1 for q in questions if q["gate"] is False)
        unmarked = sum(1 for q in questions if q["gate"] is None)
        covered = len({c for q in questions for c in q["covers"]})
        total_gate += gate
        total_gap += gap
        total_unmarked += unmarked

        text = render(kit, sheet, title, answer_format, sections, questions)

        # Parse the rendered YAML whether or not we are writing it. --check must
        # exercise everything the write path does, or it reports green over output
        # that cannot load: the first cut only reloaded after writing, and all 15
        # kits passed --check while every rendered file was unparseable.
        try:
            back = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise SheetError(f"{kit}: rendered questions.yaml does not parse: {exc}") from exc
        if len(back.get("questions") or []) != len(questions):
            raise SheetError(
                f"{kit}: rendered {len(questions)} questions, reloads "
                f"{len(back.get('questions') or [])}"
            )
        if any("answer" in (q or {}) for q in (back.get("questions") or [])):
            raise SheetError(f"{kit}: an answer slot reached the kit, which must never happen")
        for original, roundtripped in zip(questions, back["questions"]):
            # The text is the owner's own wording. Folded scalars collapse
            # newlines, so compare on whitespace-normalised text: a question that
            # arrives reworded is worse than one that fails to arrive.
            if " ".join(original["text"].split()) != " ".join(str(roundtripped["text"]).split()):
                raise SheetError(
                    f"{kit}: question {original['id']} changed wording in the round trip"
                )
        if not args.check:
            (BLOCKS / kit / "questions.yaml").write_text(text, encoding="utf-8")
        print(f"  {kit:22} {len(questions):4} questions  "
              f"{gate:3} GATE  {gap:3} GAP  {unmarked:3} unmarked  "
              f"| {len(sections):2} sections | covers {covered}/{len(quantities)} quantities")

    print(f"\n{len(kits) - len(without_sheet)} kits imported | "
          f"{total_gate} GATE + {total_gap} GAP + {total_unmarked} unmarked "
          f"= {total_gate + total_gap + total_unmarked} questions")
    if without_sheet:
        print(f"\nNO SHEET SUPPLIED — these kits keep their derived questions and say so:")
        for kit in without_sheet:
            print(f"  {kit}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SheetError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
