#!/usr/bin/env python3
"""Bulk-sync Category A platform blocks from The Fork into Cerebrum-Blocks.

POLICY (2026-06-10) — read before --apply
=======================================

This script copies Fork ``app/blocks/{name}.py`` → CB ``app/blocks/{name}.py``
for the explicit COPY list below. It does **not** touch containers, kit bundles,
or registry adapters.

Construction domain (Category D) is **out of scope** for bulk platform sync:
  - Use ``scripts/publish_construction_kit.py`` to refresh
    ``block_store/kits/construction/bundle/`` from Fork.
  - Kit install / ``CEREBRUM_DOMAIN_KITS=construction`` copies artifacts into
    the consumer ``app/`` tree at install time — not via this script.

SKIP rationale for construction files
------------------------------------
``app/containers/construction.py``
  - Not in ``app/blocks/``; this script never copies it.
  - CB copy is 8,019 LOC (Fork/bundle: 7,329). CB adds ``_safe_float`` audit
    fixes (~690 LOC). Overwriting from Fork would drop those fixes.
  - Canonical Fork source lives in the kit bundle after ``publish_construction_kit``.

``app/blocks/construction_v2.py`` (and other kit blocks)
  - Listed in SKIP_BLOCKS — synced only via kit publish + install.
  - CB app copy (497 LOC) is a slim local stub; Fork/bundle (520 LOC) imports
    ``ConstructionKnowledge`` and ``construction_types``.
  - Blind overwrite would change imports and break virgin boot unless knowledge
    modules are also installed.

See also: ``docs/block_elevation_plan_fork_sync.md`` (Category A/D).

Usage:
    python scripts/sync_blocks_from_fork.py --dry-run
    python scripts/sync_blocks_from_fork.py --apply
    python scripts/sync_blocks_from_fork.py --fork-root C:\\Users\\<owner>\\The_Fork --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FORK = Path.home() / "The_Fork"
BLOCKS_SUBDIR = Path("app/blocks")

# Category D — construction kit blocks (publish_construction_kit.py, not bulk sync).
# Includes shared filenames that would match a naive Fork∩CB glob sync.
SKIP_BLOCKS: frozenset[str] = frozenset(
    {
        # Core construction domain
        "construction_v2",
        "boq_processor",
        "spec_analyzer",
        "sympy_reasoning",
        "drawing_qto",
        "primavera_parser",
        "smart_orchestrator",
        "bim",
        "bim_extractor",
        "learning_engine",
        "recommendation_template",
        "jetson_gateway",
        "formula_executor",
        "formula_executor_v2",
        "project_reasoner",
        "_procedure_routing",
        # CB-only / review-before-overwrite (doc Category D notes)
        "llm_enhancer",
        "historical_benchmark",
    }
)

# Category A — safe to copy from Fork (explicit allowlist).
COPY_BLOCKS: tuple[str, ...] = (
    "cache_manager",
    "voice",
    "async_processor",
    "file_hasher",
    "android_drive",
    "translate",
    "vector_search",
    "web",
    "webhook",
    "pdf_v2",
    "search",
    "ocr",
    "image",
    "local_drive",
    "google_drive",
    "ocr_v2",
)

# Documented out-of-scope paths (never touched by this script).
SKIP_PATHS_NOTE: tuple[str, ...] = (
    "app/containers/construction.py",
    "block_store/kits/construction/bundle/",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bulk-sync Category A blocks from The Fork (construction kit excluded)"
    )
    parser.add_argument(
        "--fork-root",
        type=Path,
        default=DEFAULT_FORK,
        help=f"Path to The Fork clone (default: {DEFAULT_FORK})",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Print planned copies only")
    group.add_argument("--apply", action="store_true", help="Perform copies")
    args = parser.parse_args()

    fork_root: Path = args.fork_root.resolve()
    if not fork_root.is_dir():
        print(f"Fork root not found: {fork_root}", file=sys.stderr)
        return 1

    skipped_in_allowlist = [b for b in COPY_BLOCKS if b in SKIP_BLOCKS]
    if skipped_in_allowlist:
        print(f"Config error: COPY_BLOCKS ∩ SKIP_BLOCKS = {skipped_in_allowlist}", file=sys.stderr)
        return 1

    print("Out-of-scope paths (informational):")
    for p in SKIP_PATHS_NOTE:
        print(f"  SKIP {p}")

    print(f"\nSKIP_BLOCKS ({len(SKIP_BLOCKS)} kit/domain entries)")
    print(f"COPY_BLOCKS ({len(COPY_BLOCKS)} Category A entries)\n")

    copied = 0
    missing: list[str] = []

    for block in COPY_BLOCKS:
        rel = BLOCKS_SUBDIR / f"{block}.py"
        fork_src = fork_root / rel
        cb_dest = PROJECT_ROOT / rel

        if not fork_src.is_file():
            missing.append(str(rel))
            continue

        if args.dry_run:
            print(f"would copy {fork_src} -> {cb_dest}")
        else:
            cb_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fork_src, cb_dest)
            print(f"copied {rel.as_posix()}")
        copied += 1

    verb = "Would copy" if args.dry_run else "Copied"
    print(f"\n{verb} {copied}/{len(COPY_BLOCKS)} Category A blocks")

    if missing:
        print("\nMissing in Fork:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1

    if args.apply:
        print("\nPost-sync verification:")
        print("  python scripts/audit_block_standards.py")
        print("  pytest tests/blocks/ -q")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
