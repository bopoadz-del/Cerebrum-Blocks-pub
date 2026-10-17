#!/usr/bin/env python3
"""Stage K6: evaluation seeds derived from a kit's own encoding sheet.

WHAT THIS PRODUCES, AND WHAT IT CANNOT
--------------------------------------
Every question here is derived mechanically from an item that survived K1's
source gate. That makes the set **corpus-sighted by construction**: it asks
the kit about things its own sheet stated, so it measures whether the kit
still retrieves what it was given. It does not measure whether the kit is any
good at its domain.

This repo already draws that line. ``evals/blind_construction_eval.json``
records ``method: "Questions written WITHOUT sight of the ... KB entries"``
and ``run_retrieval_eval.py`` reports golden and blind separately, because a
corpus-sighted score is an upper bound and a blind score is the real one.

So a generated set is emitted with ``authored: null`` and a method string
saying exactly how it was made. **It is not a substitute for the blind
evaluation an author writes at K4**, and a kit carrying only generated seeds
has not met the bar to be published ``available`` -- ``--check`` says so and
exits non-zero.

The alternative was to invent ten plausible domain questions with plausible
answers. Those would score well, prove nothing, and be indistinguishable
from an authored set six months later.

WHAT IS DERIVABLE
-----------------
* **refusal traps** -- the trap text is the expected behaviour. A question
  that should be refused, with the refusal named. This is the strongest of
  the three: the sheet states the failure directly.
* **formulas with an expression** -- ask how the quantity is computed; the
  expression's own identifiers are the expected keywords.
* **vocabulary** -- ask what a term means; the sheet's own wording supplies
  the keywords.

Items with no expression, and every section the sheet left empty, produce
nothing. A thin sheet yields a thin eval, visibly.

Usage:
    python scripts/build_kit_eval.py --intake intake/dental.yaml
    python scripts/build_kit_eval.py --intake intake/dental.yaml --check
    python scripts/build_kit_eval.py --intake intake/dental.yaml --out e.json

Exit codes:
    0  seeds written (or present) and the kit meets the authored-eval bar
    1  seeds written, but the kit is not publishable on them alone
    2  usage error, or the intake encoded nothing to derive from
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KITS_DIR = PROJECT_ROOT / "block_store" / "kits"

SCHEMA_VERSION = "kit_seed_eval.v1"

#: The pipeline spec's bar: ten domain questions with ground truth from the
#: sheet's cited sources. Generated seeds count toward coverage but never
#: toward "authored" -- see the module docstring.
TARGET_QUESTIONS = 10

#: Retrieval depth the existing runner uses.
DEFAULT_K = 5

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")

#: Words that carry no retrieval signal. Kept deliberately short: an
#: aggressive stop-list silently strips domain terms and turns a strict
#: keyword check into a loose one.
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "are", "was",
        "were", "should", "must", "not", "never", "always", "when", "what",
        "which", "into", "onto", "than", "then", "their", "there", "his",
        "her", "its", "you", "your", "our", "who", "how", "why",
    }
)


def keywords(text: str, limit: int = 4) -> List[str]:
    """Distinctive words from the source text, in order, deduplicated."""
    seen: List[str] = []
    for word in _WORD_RE.findall(text or ""):
        low = word.lower()
        if low in _STOPWORDS or low in seen:
            continue
        seen.append(low)
        if len(seen) >= limit:
            break
    return seen


def load_intake(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    import yaml

    return yaml.safe_load(text)


def _cite(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": item.get("source", ""),
        "source_ref": item.get("source_ref", ""),
        "extracted_from": item.get("location", ""),
    }


def seeds_from_refusal_traps(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The strongest seeds: the sheet names the failure outright."""
    out = []
    for index, item in enumerate(items, start=1):
        text = item.get("text", "").strip()
        if not text:
            continue
        out.append(
            {
                "id": f"trap{index:02d}",
                "kind": "refusal",
                "question": text,
                "expected_behaviour": "refuse",
                "expected_keywords": keywords(text),
                "why": "the encoding sheet names this as a failure to refuse",
                "provenance": _cite(item),
            }
        )
    return out


def seeds_from_formulas(items: List[Dict[str, Any]]) -> tuple:
    """Ask how a quantity is computed. Skips items with no expression."""
    out, skipped = [], []
    index = 0
    for item in items:
        text = item.get("text", "").strip()
        if "=" not in text:
            skipped.append(item.get("location", "?"))
            continue
        name, expression = text.split("=", 1)
        name, expression = name.strip(), expression.strip()
        if not name or not expression:
            skipped.append(item.get("location", "?"))
            continue
        index += 1
        out.append(
            {
                "id": f"calc{index:02d}",
                "kind": "definition",
                "question": f"How is {name} calculated?",
                "expected_behaviour": "answer",
                "expected_keywords": keywords(expression),
                "why": "the expression's own identifiers must appear in the answer",
                "provenance": _cite(item),
            }
        )
    return out, skipped


def seeds_from_vocabulary(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for index, item in enumerate(items, start=1):
        text = item.get("text", "").strip()
        if not text:
            continue
        term = text.split("=", 1)[0].strip() if "=" in text else text
        body = text.split("=", 1)[1].strip() if "=" in text else text
        out.append(
            {
                "id": f"term{index:02d}",
                "kind": "vocabulary",
                "question": f"What does {term!r} mean in this domain?",
                "expected_behaviour": "answer",
                "expected_keywords": keywords(body),
                "why": "the sheet's own wording supplies the ground truth",
                "provenance": _cite(item),
            }
        )
    return out


def build_eval(intake: Dict[str, Any]) -> tuple:
    sections = intake.get("sections") or {}
    traps = seeds_from_refusal_traps(sections.get("refusal_traps") or [])
    calcs, skipped = seeds_from_formulas(sections.get("formulas") or [])
    terms = seeds_from_vocabulary(sections.get("vocabulary") or [])
    questions = traps + calcs + terms

    document = {
        "schema_version": SCHEMA_VERSION,
        "name": f"{intake.get('kit', 'kit')} seed eval",
        # Never a date. A date here would claim someone wrote these.
        "authored": None,
        "generated_by": "scripts/build_kit_eval.py",
        "method": (
            "Derived mechanically from items in the K1 intake that carried a "
            "source. CORPUS-SIGHTED BY CONSTRUCTION: these questions ask the "
            "kit about what its own sheet stated, so a good score means the "
            "kit did not lose what it was given -- not that it is good at the "
            "domain. A blind evaluation, written without sight of the corpus, "
            "is a separate authored artifact (see evals/ for the pattern) and "
            "is required before this kit can be published available."
        ),
        "k": DEFAULT_K,
        "source_intake": {
            "sheet": (intake.get("intake") or {}).get("sheet"),
            "sheet_sha256": (intake.get("intake") or {}).get("sheet_sha256"),
        },
        "coverage": {
            "refusal": len(traps),
            "definition": len(calcs),
            "vocabulary": len(terms),
            "total": len(questions),
            "target": TARGET_QUESTIONS,
        },
        "questions": questions,
    }
    return document, skipped


def assess(document: Dict[str, Any]) -> List[str]:
    """Why this kit is not publishable on these seeds alone."""
    reasons = []
    if not document.get("authored"):
        reasons.append(
            "no authored blind evaluation: these seeds are corpus-sighted and "
            "cannot establish domain quality"
        )
    total = document["coverage"]["total"]
    if total < TARGET_QUESTIONS:
        reasons.append(
            f"{total} questions derived, target is {TARGET_QUESTIONS}; the "
            f"sheet did not state enough to reach it"
        )
    if not document["coverage"]["refusal"]:
        reasons.append(
            "no refusal traps: nothing in the sheet said what the kit must "
            "decline, so nothing tests that it does"
        )
    return reasons


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Derive evaluation seeds from a K1 intake (stage K6)."
    )
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report publishability without writing anything",
    )
    args = parser.parse_args()

    if not args.intake.is_file():
        print(f"No such intake: {args.intake}", file=sys.stderr)
        return 2

    intake = load_intake(args.intake)
    kit = intake.get("kit")
    if not kit:
        print("Intake declares no kit id.", file=sys.stderr)
        return 2

    document, skipped = build_eval(intake)
    if not document["questions"]:
        print(
            f"Nothing derivable for {kit!r}: the intake carried no refusal "
            f"traps, no formulas written as 'name = expression', and no "
            f"vocabulary. A thin sheet yields a thin eval -- that is the "
            f"sheet's state, not a tool failure.",
            file=sys.stderr,
        )
        return 2

    out = args.out or (KITS_DIR / kit / "evaluation" / "golden_questions.json")
    if not args.check:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"Seeds written: {out}")

    coverage = document["coverage"]
    print(f"  questions: {coverage['total']} (target {coverage['target']})")
    print(f"    refusal   : {coverage['refusal']}")
    print(f"    definition: {coverage['definition']}")
    print(f"    vocabulary: {coverage['vocabulary']}")
    if skipped:
        print(f"  formulas with no expression, skipped: {len(skipped)}")
        for location in skipped[:5]:
            print(f"    {location}")

    reasons = assess(document)
    if reasons:
        print("  NOT PUBLISHABLE on these alone:")
        for reason in reasons:
            print(f"    - {reason}")
        print(
            "  Ship it skeleton (status draft) until an author writes the "
            "blind evaluation. That is honest; 'available' would not be."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
