#!/usr/bin/env python3
"""Stage K4: the author pass, with the reviewer's work laid out and their
sign-off recorded.

WHY THIS IS NOT AN AUTOMATION OF K4
-----------------------------------
K4 is the stage where a person takes responsibility for a kit's content. This
tool does not do that and cannot. What it does is remove the two reasons a
reviewer gets it wrong: not knowing what is outstanding, and not knowing what
each item claimed or who claimed it.

So the report shows every unresolved item **next to its citation** -- the
source kind, the reference, and the sheet cell it came from -- because
"review this formula" is not a reviewable instruction and "review this
formula, which the contributor attributes to Ops manual s4.2" is.

WHAT SIGN-OFF MEANS
-------------------
``--sign-off --reviewer <id>`` raises ``trust_tier`` to
``contributor_reviewed``, sets ``status`` to ``available``, and records who
did it and when. It refuses while any of the REVIEWER'S work is outstanding,
and the refusal lists what.

"The reviewer's work" excludes ``trust_tier`` and ``status``, because setting
those is what signing off does. An earlier version checked every K4 finding
and therefore deadlocked: a reviewer could resolve every definition, fill
every schema and author the blind evaluation, and still be refused on the
grounds that the kit was not yet signed off.

The conditions are imported from :mod:`pipeline_kit`, not restated here. Two
copies of "what K4 requires" would drift, and the failure mode of that drift
is a reviewer signing off against a checklist the pipeline still rejects --
a kit that believes it is reviewed and a gate that disagrees, with no way to
tell which is right.

``--reviewer`` is mandatory and is written into the manifest. A trust tier
whose whole meaning is "somebody vouched for this" must say who, or it
records nothing at all.

Usage:
    python scripts/review_kit.py --kit dental
    python scripts/review_kit.py --kit dental --sign-off --reviewer dr-a-hassan

Exit codes:
    0  nothing outstanding (or sign-off recorded)
    1  items outstanding, listed
    2  usage error, or no such kit
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
KITS_DIR = PROJECT_ROOT / "block_store" / "kits"

REVIEWED_TIER = "contributor_reviewed"
PUBLISHABLE_STATUS = "available"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _findings(kit: str):
    """(key, message) from pipeline_kit. Imported, never restated."""
    pipeline_kit = _load("pipeline_kit")
    pipeline_kit.KITS_DIR = KITS_DIR
    return pipeline_kit.author_pass_findings(kit), pipeline_kit.SET_BY_SIGN_OFF


def outstanding(kit: str) -> List[str]:
    """Everything K4 still requires, including what sign-off will set."""
    findings, _ = _findings(kit)
    return [message for _key, message in findings]


def blocking_sign_off(kit: str) -> List[str]:
    """What the REVIEWER must resolve before they can sign off.

    Excludes ``trust_tier`` and ``status``, because raising those is what
    signing off does. Refusing to sign off on the grounds that the kit is not
    yet signed off would deadlock the stage -- the reviewer would do every
    piece of real work and still be told no.
    """
    findings, set_by_sign_off = _findings(kit)
    return [
        message for key, message in findings if key not in set_by_sign_off
    ]


# -- what the reviewer needs to see ---------------------------------------


def _cite(provenance: Dict[str, Any]) -> str:
    kind = provenance.get("kind") or provenance.get("source") or "?"
    ref = provenance.get("reference") or provenance.get("source_ref") or "?"
    where = provenance.get("extracted_from") or ""
    return f"[{kind}: {ref}]" + (f" @ {where}" if where else "")


def definitions_needing_review(kit_dir: Path) -> List[Dict[str, Any]]:
    """Definitions a reviewer must look at, worst first.

    A null expression is the sharp case: the contributor stated something the
    scaffold could not turn into arithmetic, so it is carried as prose with a
    real citation attached. Either it becomes a formula or it stops being a
    definition -- leaving it is how a kit ends up with a sourced non-answer.
    """
    overlay = _read_json(kit_dir / "app" / "data" / "domain_definitions.json") or {}
    rows = []
    for entry in overlay.get("definitions") or []:
        if entry.get("expression") is None:
            rows.append({"why": "no expression", **entry})
        elif not entry.get("inputs"):
            rows.append({"why": "no inputs named", **entry})
    return rows


def empty_schemas(kit_dir: Path) -> List[Path]:
    return [
        path
        for path in sorted((kit_dir / "schemas").glob("*.json"))
        if not ((_read_json(path) or {}).get("properties"))
    ]


def evaluation_state(kit_dir: Path) -> Dict[str, Any]:
    document = _read_json(kit_dir / "evaluation" / "golden_questions.json") or {}
    return {
        "present": bool(document),
        "authored": document.get("authored"),
        "questions": len(document.get("questions") or []),
    }


def report(kit: str, kit_dir: Path) -> List[str]:
    todo = outstanding(kit)
    manifest = _read_json(kit_dir / "manifest.json") or {}

    print(f"\n{kit} -- author pass (K4)")
    print(f"  trust_tier : {manifest.get('trust_tier', 'unset')}")
    print(f"  status     : {manifest.get('status', 'unset')}")
    intake = manifest.get("_intake") or {}
    if intake:
        print(f"  from sheet : {intake.get('sheet')} ({(intake.get('sheet_sha256') or '')[:12]}...)")
        print(f"  contributor: {intake.get('contributor_id')}")

    pending = definitions_needing_review(kit_dir)
    if pending:
        print(f"\n  DEFINITIONS TO RESOLVE ({len(pending)})")
        for entry in pending:
            print(f"    - {entry['id']}  ({entry['why']})")
            print(f"        text : {entry.get('name', '')}")
            print(f"        cite : {_cite(entry.get('provenance') or {})}")
        print(
            "      Either write the arithmetic, or remove it -- a sourced "
            "non-answer is worse than an absent one."
        )

    blanks = empty_schemas(kit_dir)
    if blanks:
        print(f"\n  SCHEMAS WITH NO PROPERTIES ({len(blanks)})")
        for path in blanks:
            schema = _read_json(path) or {}
            print(f"    - {path.name}: {schema.get('description', '')}")
            print(f"        cite : {_cite(schema.get('x-provenance') or {})}")

    evaluation = evaluation_state(kit_dir)
    print(f"\n  EVALUATION")
    if not evaluation["present"]:
        print("    none. Run build_kit_eval.py for seeds, then author a blind set.")
    else:
        print(f"    {evaluation['questions']} question(s); authored: "
              f"{evaluation['authored'] or 'NO (seeds only)'}")
        if not evaluation["authored"]:
            print(
                "    Seeds are corpus-sighted: they prove the kit kept what it "
                "was given, not that it is any good. Write questions without "
                "sight of the corpus and set `authored` to today's date."
            )

    if todo:
        print(f"\n  OUTSTANDING ({len(todo)})")
        for note in todo:
            print(f"    - {note}")
    else:
        print("\n  Nothing outstanding. --sign-off will record the review.")
    return todo


# -- sign-off --------------------------------------------------------------


def sign_off(kit: str, kit_dir: Path, reviewer: str, when: str) -> int:
    todo = blocking_sign_off(kit)
    if todo:
        print(
            f"\nRefusing to sign off {kit!r}: {len(todo)} item(s) outstanding.",
            file=sys.stderr,
        )
        for note in todo:
            print(f"  - {note}", file=sys.stderr)
        print(
            "\nSigning off here would record that somebody vouched for content "
            "they have not finished reviewing. That record is the only thing "
            "the trust tier means.",
            file=sys.stderr,
        )
        return 1

    manifest_path = kit_dir / "manifest.json"
    manifest = _read_json(manifest_path) or {}
    manifest["trust_tier"] = REVIEWED_TIER
    manifest["status"] = PUBLISHABLE_STATUS
    manifest["review"] = {
        "reviewer": reviewer,
        "reviewed_on": when,
        "tier_before": "contributor_unverified",
        "tool": "scripts/review_kit.py",
        "note": (
            "The reviewer read the kit's content and takes responsibility for "
            "it. Raised by tool only after every K4 condition was met."
        ),
    }
    manifest.pop("_trust_tier_note", None)
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"\n{kit}: trust_tier -> {REVIEWED_TIER}, status -> {PUBLISHABLE_STATUS}")
    print(f"  reviewer: {reviewer}  on {when}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Walk the K4 author pass and record its sign-off."
    )
    parser.add_argument("--kit", required=True)
    parser.add_argument("--sign-off", action="store_true")
    parser.add_argument(
        "--reviewer",
        help="Identity recorded against the sign-off. Required with --sign-off.",
    )
    parser.add_argument("--on", default=None, help="ISO date (defaults to today)")
    args = parser.parse_args()

    kit = args.kit.strip().lower()
    kit_dir = KITS_DIR / kit
    if not kit_dir.is_dir():
        print(f"No kit at {kit_dir}", file=sys.stderr)
        return 2

    if args.sign_off:
        if not args.reviewer:
            print(
                "--reviewer is required with --sign-off. A trust tier whose "
                "meaning is 'somebody vouched for this' must say who.",
                file=sys.stderr,
            )
            return 2
        report(kit, kit_dir)
        return sign_off(kit, kit_dir, args.reviewer, args.on or date.today().isoformat())

    return 1 if report(kit, kit_dir) else 0


if __name__ == "__main__":
    raise SystemExit(main())
