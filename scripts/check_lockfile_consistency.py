#!/usr/bin/env python3
"""Fail-closed lockfile consistency: a pin change without a lock delta fails.

WHY THIS EXISTS
---------------
``requirements.txt`` and ``frontend/package.json`` are the declared pin
files. Each has a lock that CI / install paths are supposed to track:

  requirements.txt          <-> requirements.lock
  frontend/package.json     <-> frontend/package-lock.json

A PR that bumps a pin and leaves the lock untouched is a green install of
a graph nobody resolved. That is how the lock rot into a souvenir.

This gate is a *delta* check, not a resolver. It refuses a pin path in
the changed set whose lock is absent from that set. It also refuses a
missing declared lock on disk. It does not invent a lock for pin files
that have never had one.

UNPAIRED (inspected; not invented)
----------------------------------
  sandbox-runner/requirements.txt
  block_store/kits/universal_kernel/requirements.txt
  block_registry/marker/requirements.txt
  cli/pyproject.toml

Exit 1 (fail closed) when:

  * a declared lock is missing from the tree
  * a pin path changed and its lock did not
  * the changed set cannot be determined (do not skip)

Exit 0 when the changed set is empty, lock-only, or pin+lock together.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PAIRS: tuple[tuple[str, str], ...] = (
    ("requirements.txt", "requirements.lock"),
    ("frontend/package.json", "frontend/package-lock.json"),
)

UNPAIRED_PINS: tuple[str, ...] = (
    "sandbox-runner/requirements.txt",
    "block_store/kits/universal_kernel/requirements.txt",
    "block_registry/marker/requirements.txt",
    "cli/pyproject.toml",
)

_ZERO_SHA = "0" * 40


def normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def missing_locks(repo_root: Path) -> list[str]:
    missing = []
    for pin, lock in PAIRS:
        if not (repo_root / lock).is_file():
            missing.append(lock)
        if not (repo_root / pin).is_file():
            missing.append(pin)
    return missing


def pin_without_lock_delta(changed: set[str]) -> list[tuple[str, str]]:
    hits = []
    for pin, lock in PAIRS:
        if pin in changed and lock not in changed:
            hits.append((pin, lock))
    return hits


def git_changed_paths(base: str, head: str, repo_root: Path) -> set[str] | None:
    if not base or base == _ZERO_SHA or set(base) == {"0"}:
        return None
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "diff",
                "--name-only",
                "--diff-filter=ACDMRTUXB",
                f"{base}...{head}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return {normalize(line) for line in proc.stdout.splitlines() if line.strip()}


def resolve_changed(
    *,
    explicit: list[str] | None,
    base: str | None,
    head: str,
    repo_root: Path,
    env: dict[str, str],
) -> set[str] | None:
    if explicit is not None:
        return {normalize(p) for p in explicit}
    resolved_base = (
        base
        or env.get("LOCKFILE_BASE")
        or env.get("GITHUB_BASE_SHA")
        or ""
    ).strip()
    resolved_head = (head or env.get("LOCKFILE_HEAD") or "HEAD").strip()
    if not resolved_base:
        return None
    return git_changed_paths(resolved_base, resolved_head, repo_root)


def evaluate(repo_root: Path, changed: set[str] | None) -> int:
    missing = missing_locks(repo_root)
    if missing:
        sys.stderr.write(
            "LOCKFILE_CONSISTENCY_FAIL missing declared pin/lock: "
            + ", ".join(missing)
            + "\n"
        )
        return 1
    if changed is None:
        sys.stderr.write(
            "LOCKFILE_CONSISTENCY_FAIL cannot determine changed set "
            "(pass --changed or LOCKFILE_BASE; fail-closed, not skip)\n"
        )
        return 1
    hits = pin_without_lock_delta(changed)
    if hits:
        for pin, lock in hits:
            sys.stderr.write(
                f"LOCKFILE_CONSISTENCY_FAIL pin changed without lock delta: "
                f"{pin} (expected {lock})\n"
            )
        return 1
    sys.stdout.write("LOCKFILE_CONSISTENCY_OK\n")
    return 0


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--changed",
        nargs="*",
        default=None,
        help="Synthetic / explicit changed paths (repo-relative). "
        "An empty list is an empty delta, not 'undetermined'.",
    )
    parser.add_argument("--base", default=None, help="Git base SHA or ref")
    parser.add_argument("--head", default="HEAD", help="Git head SHA or ref")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root (default: cwd)",
    )
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    environ = env if env is not None else dict(os.environ)
    changed = resolve_changed(
        explicit=args.changed,
        base=args.base,
        head=args.head,
        repo_root=repo_root,
        env=environ,
    )
    return evaluate(repo_root, changed)


if __name__ == "__main__":
    raise SystemExit(main())
