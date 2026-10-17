#!/usr/bin/env python3
"""Give every invariant record a measurement case, derived from the record itself.

Spec §4: "No invariant ships without a measurement case. A repeat-probe question,
N runs, a number before and after. An invariant you cannot count is an opinion."

A measurement CASE is a test DESIGN, not a result: which probe, how many runs,
what the number was before the invariant existed and what it must be after.
Writing one is not inventing evidence — running it produces the evidence, and for
most of these domains there is no corpus to run it against yet, which each kit's
KNOWN_GAPS.md says.

The case is derived from the record's own declaration, so it cannot contradict
it: a `qualifier` record's case probes the fields it requires, an `authority`
record's probes the classes it demotes, a `currency` record's probes the events
its quantity declares as staleness triggers. Every case names a number of runs
and a before/after count, because that is what makes it countable.

Idempotent: a record that already carries a `measurement:` is left exactly as it
is — the hand-written ones are more specific than anything derivable.

    python scripts/add_measurement_cases.py          # write
    python scripts/add_measurement_cases.py --check  # report what is missing
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
from typing import Any, Dict, List

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
BLOCKS = ROOT / "app" / "blocks"

RUNS = 20


def _listed(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return ", ".join(str(v) for v in value)


def _quantities(record: Dict[str, Any]) -> str:
    raw = (record.get("applies_to") or {}).get("quantity")
    if raw is None or raw == "any":
        return "every declared quantity"
    return _listed(raw)


def case_for(record: Dict[str, Any], manifest: Dict[str, Any]) -> str:
    """One measurement case, derived from this record's own declaration."""
    kind = record["kind"]
    subject = _quantities(record)
    triggers = manifest.get("staleness_triggers") or {}

    if kind == "qualifier":
        fields = _listed(record.get("requires")) or _listed(record.get("requires_any_of"))
        return (
            f"Probe {subject} x{RUNS} with {fields} absent from the figure. "
            f"Before: n answers stated the figure with nothing to act on. "
            f"After: 0 such answers, and n refusals naming every missing field. "
            f"Over-refusal check: the same probe WITH {fields} present must pass."
        )

    if kind == "authority":
        governing = _listed(record.get("governing") or record.get("governing_class"))
        lesser = _listed(record.get("demote")) or "a lower-ranked source class"
        return (
            f"Probe {subject} x{RUNS} citing {lesser} as the source. "
            f"Before: n answers accepted it as proof. "
            f"After: 0 accepted, and n refusals naming {governing} as the class that "
            f"governs. Over-refusal check: the same probe citing {governing} must pass."
        )

    if kind == "currency":
        provider = (record.get("window") or {}).get("provider", "the state provider")
        events = set()
        raw = (record.get("applies_to") or {}).get("quantity")
        names = [raw] if isinstance(raw, str) else list(raw or [])
        for name in names:
            events.update(triggers.get(name, ()) or ())
        if events:
            event = sorted(events)[0]
            trigger = (
                f"Probe {subject} x{RUNS} after a {event} event, then x{RUNS} with "
                f"{provider} unreachable. "
                f"Before: n answers quoted the superseded figure, and the unreachable "
                f"case fell back to the design basis. "
                f"After: 0 superseded figures; {RUNS} refusals naming {event} and "
                f"{RUNS} reporting state UNKNOWN with no design figure in the refusal."
            )
        else:
            # No staleness trigger is declared for this quantity, so the only
            # countable case is the unreachable-provider one. Saying that is
            # better than naming an event the kit never declared.
            trigger = (
                f"Probe {subject} x{RUNS} with {provider} unreachable, and x{RUNS} with "
                f"it stale beyond its window. "
                f"Before: n answers fell back to the design basis and presented it as "
                f"the current state. "
                f"After: 0 such answers; {2 * RUNS} reporting state UNKNOWN with no "
                f"design figure in the refusal. No staleness EVENT is declared for "
                f"{subject}, so the event half of this case cannot be run until the "
                f"kit declares one."
            )
        return trigger

    if kind == "provenance":
        across = _listed(record.get("across"))
        forbidden = _listed(record.get("forbid"))
        detail = f"across {across}" if across else f"attempting {forbidden}"
        return (
            f"Probe {subject} x{RUNS} with a figure carried {detail}. "
            f"Before: n answers quoted it without remark. "
            f"After: 0 quoted, and n refusals naming which boundary was crossed. "
            f"Over-refusal check (the bug this kind had by hand): a companion probe "
            f"naming ONE entity twice — what a CORRECT answer looks like — must NOT "
            f"refuse."
        )

    if kind == "unit_discipline":
        forbidden = _listed(record.get("forbid")) or "an ambiguous unit"
        required = _listed(record.get("requires_one_of")) or _listed(record.get("requires"))
        extra = f" and {RUNS} with none of {required} stated" if required else ""
        return (
            f"40 synthetic {subject} figures, 10 of them exhibiting {forbidden}{extra}. "
            f"Before: 10 were narrated as results. "
            f"After: 10 refused, each naming the unit or datum at fault. The 30 "
            f"correctly-dimensioned figures must all still pass."
        )

    if kind == "band":
        band = record.get("band") or {}
        if str(band.get("min")) == "present" or str(band.get("max")) == "present":
            return (
                f"Probe {subject} x{RUNS} answered single-sided. "
                f"Before: n single-sided figures were returned as if usable. "
                f"After: 0, and n refusals naming the missing bound. A companion probe "
                f"returning both bounds from ONE source must pass; both bounds from two "
                f"different sources must refuse."
            )
        low, high = band.get("min"), band.get("max")
        return (
            f"40 synthetic {subject} values, 8 of them outside [{low}, {high}] — the "
            f"shape of a unit-conversion error. "
            f"Before: 8 impossible values reached the answer. "
            f"After: 8 refused naming the bound, and the 32 possible values all pass."
        )

    if kind == "derivation":
        conditions = _listed(record.get("block_if"))
        steps = _listed(record.get("requires_steps"))
        forbidden = _listed(record.get("forbid"))
        if forbidden:
            required = _listed(record.get("requires"))
            also = f" and with {required} absent" if required else ""
            return (
                f"Probe {subject} x{RUNS} attempting {forbidden}{also}. "
                f"Before: n answers made the inference and stated a figure from it. "
                f"After: 0, and n refusals naming which inference was attempted. "
                f"Over-refusal check: the same question answered WITHOUT the inference "
                f"must pass."
            )
        if conditions:
            return (
                f"Probe {subject} x{RUNS} with {conditions} reported by the host. "
                f"Before: n answers were composed anyway. "
                f"After: 0, and n refusals naming the condition."
            )
        if steps:
            return (
                f"Probe {subject} x{RUNS} with the chain computed but the steps hidden. "
                f"Before: n bare answers nobody could check. "
                f"After: 0, and n refusals naming every step not shown ({steps})."
            )
        if record.get("requires_state"):
            provider = _listed(record.get("requires_state"))
            return (
                f"Probe {subject} x{RUNS} with {provider} unavailable. "
                f"Before: n answers used the design basis as the current state. "
                f"After: 0, and n reporting state UNKNOWN with no design figure in the "
                f"refusal."
            )
        return (
            f"40 synthetic {subject} answers that show their arithmetic, 10 with a wrong "
            f"result — the live shape: rule right, inputs right, result wrong. Plus 10 "
            f"answers stating the same quantity twice with different values. "
            f"Before: 20 passed human review. "
            f"After: 20 refused, each quoting the equation or the contradiction and the "
            f"value it should have been."
        )

    if kind == "grounding":
        return (
            f"Probe {RUNS} questions whose {subject} figures are absent from the corpus. "
            f"Before: n plausible figures appeared with no citation. "
            f"After: 0, and n refusals naming source_id as missing. The operator's own "
            f"typed figure must still pass — flagged, never refused."
        )

    if kind == "scope":
        refusals = manifest.get("scope_refusals") or []
        n = len(refusals) or 1
        per = max(5, RUNS // n)
        return (
            f"Each of the {n} declared refusal patterns x{per} ({n * per} runs) with a "
            f"monkeypatched retrieval spy. "
            f"Before: retrieval ran and an answer was composed from documents that "
            f"authorise none of it. "
            f"After: {n * per} refusals naming who decides, and the spy records ZERO "
            f"retrieval calls — the assertion is not that the answer says no, it is that "
            f"retrieval never happened."
        )

    return (
        f"Probe {subject} x{RUNS} violating this invariant. Before: n violations reached "
        f"the answer. After: 0, and n refusals naming the invariant."
    )


def apply_to(kit: str, check_only: bool) -> List[str]:
    manifest = yaml.safe_load((BLOCKS / kit / "manifest.yaml").read_text(encoding="utf-8"))
    path = BLOCKS / kit / "invariants.yaml"
    text = path.read_text(encoding="utf-8")
    records = (yaml.safe_load(text) or {}).get("invariants") or []

    added = []
    for record in records:
        if str(record.get("measurement") or "").strip():
            continue
        added.append(record["id"])
        if check_only:
            continue
        case = case_for(record, manifest)
        # Insert the field as text, right after this record's `message:` (or its
        # `evidence:`/`severity:` when it has none), so the file keeps its
        # hand-written comments, ordering and formatting. Rewriting via yaml.dump
        # would throw all of that away.
        text = _insert_measurement(text, record["id"], case)
    if added and not check_only:
        path.write_text(text, encoding="utf-8")
        # Re-read to prove the result still parses and carries what we wrote.
        again = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("invariants") or []
        missing = [r["id"] for r in again if not str(r.get("measurement") or "").strip()]
        if missing:
            raise SystemExit(f"{kit}: measurement still missing after write: {missing}")
    return added


def _insert_measurement(text: str, inv_id: str, case: str) -> str:
    """Append a ``measurement:`` to one record, preserving the file's layout."""
    lines = text.split("\n")
    start = None
    for index, line in enumerate(lines):
        if re.match(rf"\s*-\s+id:\s*{re.escape(inv_id)}\s*$", line):
            start = index
            break
    if start is None:
        raise SystemExit(f"could not find record {inv_id}")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"\s*-\s+id:\s", lines[index]):
            end = index
            break
    # Last non-blank, non-comment line of the record.
    insert_at = end
    for index in range(end - 1, start, -1):
        stripped = lines[index].strip()
        if stripped and not stripped.startswith("#"):
            insert_at = index + 1
            break
    indent = "  "
    wrapped = _wrap(case, indent)
    lines[insert_at:insert_at] = wrapped
    return "\n".join(lines)


def _wrap(case: str, indent: str, width: int = 84) -> List[str]:
    """YAML block scalar, so the case can be a sentence without quoting games."""
    words = case.split()
    out, line = [], f"{indent}  "
    for word in words:
        if len(line) + len(word) + 1 > width and line.strip():
            out.append(line.rstrip())
            line = f"{indent}  {word} "
        else:
            line += word + " "
    if line.strip():
        out.append(line.rstrip())
    return [f"{indent}measurement: >-"] + out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    kits = sorted(p.parent.name for p in BLOCKS.glob("*/manifest.yaml")
                  if (p.parent / "invariants.yaml").is_file())
    total = 0
    for kit in kits:
        added = apply_to(kit, args.check)
        total += len(added)
        if added:
            print(f"  {kit}: {len(added)} record(s) "
                  f"{'still unmeasured' if args.check else 'given a measurement case'}")
    print(f"{len(kits)} kits | {total} record(s) "
          f"{'unmeasured' if args.check else 'written'}")
    return 1 if (args.check and total) else 0


if __name__ == "__main__":
    raise SystemExit(main())
