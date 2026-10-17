#!/usr/bin/env python3
"""Publish the construction container kit from The Fork into Cerebrum Block Store.

Usage:
    python scripts/publish_construction_kit.py
    python scripts/publish_construction_kit.py --fork-root C:\\Users\\<owner>\\The_Fork

Copies Fork-authored artifacts into block_store/kits/construction/bundle/
so GET /store/containers lists bundle_ready=true and install can run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FORK = Path.home() / "The_Fork"
KIT_ID = "construction"
MANIFEST_PATH = PROJECT_ROOT / "block_store" / "kits" / KIT_ID / "manifest.json"
BUNDLE_DIR = PROJECT_ROOT / "block_store" / "kits" / KIT_ID / "bundle"
FORK_REPO = "bopoadz-del/The_Fork"
FORK_MARKER = "app"


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _artifact_src(item: Any) -> str | None:
    if not isinstance(item, Mapping) or not item.get("src"):
        return None
    src = item["src"]
    if not isinstance(src, str):
        return None
    return src


def load_artifacts(manifest_path: Path) -> tuple[list[str] | None, str | None]:
    """Return (src paths, error). Exactly one of the two is set."""
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"Cannot read kit manifest: {manifest_path}\n{exc}"

    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, (
            f"Kit manifest is not valid JSON: {manifest_path}\n"
            f"{exc}\n"
            "Fix the JSON (trailing commas, missing quotes) and retry."
        )

    if not isinstance(manifest, dict):
        return None, (
            f"Kit manifest must be a JSON object: {manifest_path}\n"
            f"Got {type(manifest).__name__}."
        )

    artifacts = manifest.get("artifacts") or []
    if not isinstance(artifacts, list):
        return None, (
            f"Kit manifest 'artifacts' must be a list of "
            f"{{src, dest}} objects: {manifest_path}"
        )
    if not artifacts:
        return None, f"No artifacts listed in {manifest_path}"

    srcs: list[str] = []
    for index, item in enumerate(artifacts):
        src = _artifact_src(item)
        if src is None:
            return None, (
                f"Kit manifest artifact #{index} is malformed "
                f"(need a non-empty string 'src'): {item!r}\n"
                f"in {manifest_path}"
            )
        srcs.append(src)
    return srcs, None


def validate_fork_root(fork_root: Path) -> str | None:
    """Return an actionable error if *fork_root* is missing or not a Fork tree."""
    if not fork_root.exists():
        return (
            f"Fork root not found: {fork_root}\n"
            f"Pass --fork-root to a local clone of {FORK_REPO} "
            f"(expected layout includes an {FORK_MARKER}/ directory)."
        )
    if not fork_root.is_dir():
        return (
            f"Fork root is not a directory: {fork_root}\n"
            f"Pass --fork-root to a local clone of {FORK_REPO}."
        )
    if not (fork_root / FORK_MARKER).is_dir():
        return (
            f"Fork root is not a The_Fork tree: {fork_root}\n"
            f"Expected {fork_root / FORK_MARKER} to exist. "
            f"Clone https://github.com/{FORK_REPO} or point --fork-root at that clone."
        )
    return None


def publish(
    fork_root: Path,
    *,
    manifest_path: Path | None = None,
    bundle_dir: Path | None = None,
    dry_run: bool = False,
    refresh: bool = False,
) -> int:
    """Copy manifest artifacts from a Fork tree into the construction kit bundle.

    Paths default to the store's construction kit. Tests pass a fixture
    manifest and a temp bundle so this never needs a network clone.

    ``refresh`` copies every artifact present in the Fork checkout and retains
    paths already in ``bundle/`` when Fork no longer ships them (the
    construction monolith and CLI were removed from Fork but remain in the
    store bundle). Exit is still non-zero if any declared artifact is absent
    from both Fork and bundle.
    """
    manifest_path = Path(manifest_path or MANIFEST_PATH)
    bundle_dir = Path(bundle_dir or BUNDLE_DIR)
    fork_root = Path(fork_root).resolve()

    error = validate_fork_root(fork_root)
    if error:
        return _fail(error)
    if not manifest_path.exists():
        return _fail(
            f"Kit manifest missing: {manifest_path}\n"
            "Expected block_store/kits/construction/manifest.json."
        )

    artifacts, error = load_artifacts(manifest_path)
    if error:
        return _fail(error)
    assert artifacts is not None

    copied = 0
    missing: list[str] = []
    retained: list[str] = []

    for rel_src in artifacts:
        fork_src = fork_root / rel_src
        bundle_dest = bundle_dir / rel_src

        if not fork_src.exists():
            if refresh and bundle_dest.exists():
                if dry_run:
                    print(f"would keep {rel_src} (not in Fork, retained from bundle)")
                else:
                    print(f"kept {rel_src} (not in Fork, retained from bundle)")
                retained.append(rel_src)
                copied += 1
                continue
            missing.append(rel_src)
            continue

        if dry_run:
            print(f"would copy {fork_src} -> {bundle_dest}")
            copied += 1
            continue

        bundle_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fork_src, bundle_dest)
        print(f"copied {rel_src}")
        copied += 1

    if missing:
        print(
            f"\nFork root is missing declared artifacts "
            f"({len(missing)} missing) under {fork_root}:",
            file=sys.stderr,
        )
        for rel in missing:
            print(f"  - {rel}", file=sys.stderr)
        print(
            f"The path does not match the construction kit manifest. "
            f"Check --fork-root or add the files to the {FORK_REPO} tree.",
            file=sys.stderr,
        )
    elif retained:
        print(
            f"\nRetained {len(retained)} artifact(s) from bundle/ because Fork "
            f"no longer ships them. Update the manifest when Fork and the store "
            f"layout converge.",
            file=sys.stderr,
        )
        for rel in retained:
            print(f"  - {rel}", file=sys.stderr)

    total = len(artifacts)
    print(f"\n{'Would copy' if dry_run else 'Copied'} {copied}/{total} artifacts")

    if not dry_run and not missing:
        present = all((bundle_dir / rel).exists() for rel in artifacts)
        print(f"bundle_ready={present}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        blocks = manifest.get("blocks") or []
        print(f"blocks_registered={len(blocks)}")

    if missing:
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish construction kit from The Fork")
    parser.add_argument(
        "--fork-root",
        type=Path,
        default=DEFAULT_FORK,
        help=f"Path to The Fork clone (default: {DEFAULT_FORK})",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Override kit manifest path (tests / fixtures)",
    )
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        default=None,
        help="Override bundle output directory (tests / fixtures)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions only")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Copy what Fork has and retain bundle/ copies for paths Fork dropped",
    )
    args = parser.parse_args(argv)

    return publish(
        args.fork_root,
        manifest_path=args.manifest,
        bundle_dir=args.bundle_dir,
        dry_run=args.dry_run,
        refresh=args.refresh,
    )


if __name__ == "__main__":
    raise SystemExit(main())
