#!/usr/bin/env python3
"""The kit pipeline end to end, and an honest answer to "where is it stuck?"

Seven scripts became hard to hold in one head, and the interesting question
is never "did stage K3 succeed" -- it is "what is between this sheet and a
kit a client can install". This runs the automatable stages in order and
answers that.

THE PIPELINE DOES NOT COMPLETE ON ITS OWN, BY DESIGN
K4 is a person. A kit that has been scaffolded from one contributor's sheet
has had no reviewer: its trust tier is ``contributor_unverified``, its
schemas are empty, its ``flow`` is inherited from the template, and its only
evaluation is corpus-sighted. Every one of those is a claim somebody has to
make rather than a computation somebody can run.

So ``BLOCKED ON K4`` is this tool's normal terminal state, not a failure. It
prints what a reviewer has to do, and it will not describe a kit as ready
until they have done it. A pipeline that reported "complete" here would be
inviting the one outcome the whole design refuses -- a kit on the shelf whose
content nobody vouched for.

Stage map:
    K1  intake        scripts/intake_kit.py       sheet -> sourced items
    K2  formula fold  (K3 emits the overlay)      items -> grounded definitions
    K3  scaffold      scripts/scaffold_kit.py     intake -> kit directory
    K4  author pass   A PERSON                    review, tier, flow, schemas
    K5  publish       scripts/publish_kit.py      kit -> bundle/
    K6  eval          scripts/build_kit_eval.py   intake -> eval seeds
    K7  certify       scripts/audit_kit_composition.py

Usage:
    python scripts/pipeline_kit.py --sheet dental.xlsx --kit dental \\
        --contributor dr-a-hassan
    python scripts/pipeline_kit.py --status --kit dental

Exit codes:
    0  the kit is publishable: authored, vouched for, complete
    1  progress made; blocked on a stage that is named
    2  usage error, or a stage failed in a way that stops the run
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
KITS_DIR = PROJECT_ROOT / "block_store" / "kits"

OK = "OK"
ATTENTION = "ATTENTION"
BLOCKED = "BLOCKED"
NOT_REACHED = "-"


def _load(name: str):
    """Import a sibling script by path.

    By path rather than by name because scripts/ is not a package and is only
    on sys.path when a file in it is the entry point -- the same assumption
    that broke publish_kit's audit import when it was called as a module.
    """
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Stage:
    def __init__(self, key: str, title: str):
        self.key = key
        self.title = title
        self.status = NOT_REACHED
        self.detail = ""
        self.todo: List[str] = []

    def set(self, status: str, detail: str = "", todo: Optional[List[str]] = None):
        self.status = status
        self.detail = detail
        self.todo = todo or []
        return self


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# -- the stages ------------------------------------------------------------


def run_intake(sheet: Path, kit: str, contributor: str, out: Path, stage: Stage):
    intake_kit = _load("intake_kit")
    reader = intake_kit._READERS.get(sheet.suffix.lower())
    if reader is None:
        stage.set(BLOCKED, f"no reader for {sheet.suffix}")
        return None
    items, unmapped = reader(sheet, dict(intake_kit.SECTION_ALIASES), contributor)
    kept, dropped = intake_kit.apply_source_gate(items)
    if not kept:
        stage.set(
            BLOCKED,
            f"every item was dropped ({len(dropped)}); nothing carried a source",
            ["fix the sheet's source and reference columns, then re-run"],
        )
        return None

    document = intake_kit.build_intake(
        kit, sheet, kept, dropped, unmapped, contributor, "pipeline"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    intake_kit.write_intake(document, out)

    detail = f"{len(kept)} encoded"
    todo = []
    if dropped:
        detail += f", {len(dropped)} dropped"
        todo.append(f"{len(dropped)} item(s) had no source and were not encoded")
    if unmapped:
        todo.append(f"{len(unmapped)} section(s) unmapped")
    stage.set(ATTENTION if todo else OK, detail, todo)
    return document


def run_scaffold(intake_path: Path, kit: str, stage: Stage, force: bool):
    scaffold_kit = _load("scaffold_kit")
    kit_dir = KITS_DIR / kit
    if kit_dir.exists() and not force:
        stage.set(
            ATTENTION,
            "kit directory already exists; left untouched",
            ["re-run with --force to regenerate (this overwrites author edits)"],
        )
        return kit_dir

    argv = ["scaffold_kit.py", "--intake", str(intake_path)]
    if force:
        argv.append("--force")
    saved, sys.argv = sys.argv, argv
    try:
        code = scaffold_kit.main()
    finally:
        sys.argv = saved

    manifest = _read_json(kit_dir / "manifest.json") or {}
    overlay = _read_json(kit_dir / "app" / "data" / "domain_definitions.json") or {}
    detail = (
        f"{len(overlay.get('definitions') or [])} definitions, "
        f"status={manifest.get('status')}"
    )
    stage.set(ATTENTION if code == 1 else OK, detail,
              ["some items need the author -- see scaffold output"] if code == 1 else [])
    return kit_dir


def run_eval(intake_path: Path, kit: str, stage: Stage):
    build_kit_eval = _load("build_kit_eval")
    intake = build_kit_eval.load_intake(intake_path)
    document, skipped = build_kit_eval.build_eval(intake)
    if not document["questions"]:
        stage.set(
            BLOCKED,
            "nothing derivable from the sheet",
            ["the sheet stated no refusal traps, formulas or vocabulary"],
        )
        return document

    out = KITS_DIR / kit / "evaluation" / "golden_questions.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")

    coverage = document["coverage"]
    reasons = build_kit_eval.assess(document)
    stage.set(
        ATTENTION if reasons else OK,
        f"{coverage['total']}/{coverage['target']} questions (seeds)",
        reasons,
    )
    return document


#: K4 findings a reviewer must resolve themselves, versus state that the
#: sign-off itself writes. review_kit filters on these keys: refusing to sign
#: off because trust_tier is still unraised would be circular, since raising
#: it is what signing off does.
SET_BY_SIGN_OFF = ("trust_tier", "status")


def author_pass_findings(kit: str):
    """(key, message) for everything K4 still requires.

    Keyed rather than flat so callers can tell "the reviewer has work left"
    from "this kit has not been signed off yet". Both are reasons the kit is
    not ready; only the first is a reason a reviewer cannot proceed.
    """
    scaffold_kit = _load("scaffold_kit")
    kit_dir = KITS_DIR / kit
    manifest = _read_json(kit_dir / "manifest.json") or {}
    findings = []

    tier = manifest.get("trust_tier", "")
    if tier == scaffold_kit.SCAFFOLD_TRUST_TIER or not tier:
        findings.append((
            "trust_tier",
            f"trust_tier is {tier or 'unset'}: a reviewer must read the content "
            f"and raise it to contributor_reviewed",
        ))
    if manifest.get("status") == scaffold_kit.SCAFFOLD_STATUS:
        findings.append((
            "status",
            "status is draft: not installable until the kit is complete",
        ))

    empty_schemas = [
        p.name
        for p in sorted((kit_dir / "schemas").glob("*.json"))
        if not ((_read_json(p) or {}).get("properties"))
    ]
    if empty_schemas:
        findings.append((
            "schemas",
            f"{len(empty_schemas)} schema(s) have no properties: "
            f"{', '.join(empty_schemas[:3])}",
        ))

    evaluation = _read_json(kit_dir / "evaluation" / "golden_questions.json") or {}
    if evaluation and not evaluation.get("authored"):
        findings.append((
            "evaluation",
            "the only evaluation is corpus-sighted seeds; a blind evaluation "
            "must be authored before quality can be claimed",
        ))
    return findings


def check_author_pass(kit: str, stage: Stage):
    """K4. Everything here is a claim, not a computation."""
    todo = [message for _key, message in author_pass_findings(kit)]
    stage.set(BLOCKED if todo else OK, "a person, not a script", todo)
    return not todo


def run_publish_check(kit: str, stage: Stage):
    publish_kit = _load("publish_kit")
    kit_dir = KITS_DIR / kit
    manifest = _read_json(kit_dir / "manifest.json") or {}
    artifacts = manifest.get("artifacts") or []
    if not artifacts:
        stage.set(
            NOT_REACHED,
            "kit declares no install artifacts yet",
            ["K4 decides what the kit installs"],
        )
        return False
    missing = publish_kit.missing_from_bundle(kit_dir / "bundle", artifacts)
    if missing:
        stage.set(BLOCKED, f"{len(missing)} declared artifact(s) not in bundle/",
                  [f"run publish_kit.py --domain {kit}"])
        return False
    stage.set(OK, f"{len(artifacts)} artifacts bundled")
    return True


def run_certify(kit: str, stage: Stage):
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    from audit_kit_composition import (  # noqa: E402
        MODULES_DIR,
        REGISTRY_DIR,
        _dirs,
        _modules,
        audit_kit,
        load_known,
    )

    known = _dirs(REGISTRY_DIR) | _modules(MODULES_DIR)
    registered = load_known()
    findings = [
        (code, detail)
        for code, detail in audit_kit(kit, str(KITS_DIR), known)
        if f"{kit} :: {code}" not in registered
    ]
    if findings:
        stage.set(
            BLOCKED,
            f"{len(findings)} composition finding(s)",
            [f"{code}: {detail}" for code, detail in findings[:5]],
        )
        return False
    stage.set(OK, "composition declared and consistent")
    return True


# -- reporting -------------------------------------------------------------


def report(kit: str, stages: List[Stage]) -> int:
    width = max(len(s.title) for s in stages)
    print(f"\n{kit}")
    for stage in stages:
        print(f"  {stage.key}  {stage.title:<{width}}  {stage.status:<9} {stage.detail}")
        for note in stage.todo:
            print(f"       - {note}")

    blocked = [s for s in stages if s.status == BLOCKED]
    if blocked:
        first = blocked[0]
        print(f"\nBlocked at {first.key} ({first.title}).")
        if first.key == "K4":
            print(
                "That is the expected terminal state for an automated run: K4 is "
                "a person taking responsibility for the content. The kit is not "
                "ready, and nothing here will make it ready."
            )
        return 1
    if any(s.status == ATTENTION for s in stages):
        print("\nNo stage is blocked, but items need attention (listed above).")
        return 1
    print(f"\n{kit} is publishable: authored, vouched for, and complete.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the kit pipeline end to end.")
    parser.add_argument("--kit", required=True)
    parser.add_argument("--sheet", type=Path)
    parser.add_argument("--contributor")
    parser.add_argument("--intake", type=Path, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--status",
        action="store_true",
        help="Report where an existing kit stands without running anything",
    )
    args = parser.parse_args()

    kit = args.kit.strip().lower()
    stages = [
        Stage("K1", "intake"),
        Stage("K3", "scaffold"),
        Stage("K6", "eval seeds"),
        Stage("K4", "author pass"),
        Stage("K5", "publish"),
        Stage("K7", "certify"),
    ]
    by_key = {s.key: s for s in stages}

    if args.status:
        if not (KITS_DIR / kit).exists():
            print(f"No kit at {KITS_DIR / kit}", file=sys.stderr)
            return 2
        for key in ("K1", "K3", "K6"):
            by_key[key].set(NOT_REACHED, "not run in --status mode")
        check_author_pass(kit, by_key["K4"])
        run_publish_check(kit, by_key["K5"])
        run_certify(kit, by_key["K7"])
        return report(kit, stages)

    if not args.sheet or not args.contributor:
        print("--sheet and --contributor are required unless --status", file=sys.stderr)
        return 2
    if not args.sheet.is_file():
        print(f"No such sheet: {args.sheet}", file=sys.stderr)
        return 2

    intake_path = args.intake or (PROJECT_ROOT / "intake" / f"{kit}.yaml")
    if run_intake(args.sheet, kit, args.contributor, intake_path, by_key["K1"]) is None:
        return report(kit, stages)

    run_scaffold(intake_path, kit, by_key["K3"], args.force)
    run_eval(intake_path, kit, by_key["K6"])
    check_author_pass(kit, by_key["K4"])
    run_publish_check(kit, by_key["K5"])
    run_certify(kit, by_key["K7"])
    return report(kit, stages)


if __name__ == "__main__":
    raise SystemExit(main())
