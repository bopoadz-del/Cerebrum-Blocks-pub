#!/usr/bin/env python3
"""Kits whose bundle mirrors any of the given repo paths.

Used by .github/workflows/re-sign.yml after a re-sign rewrites
block_registry/*/block.json: a kit is affected when it is ``available`` and
its manifest declares an artifact whose ``src`` is one of the changed paths.
Selection is by manifest data only -- no kit names live here or in the
workflow -- so the same line is right for any set of kits.

Usage:
    python scripts/affected_kits.py <repo-relative path> [...]   # one kit id per line
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable, List

ROOT = Path(__file__).resolve().parents[1]


def affected_kits(changed: Iterable[str], kits_dir: Path) -> List[str]:
    wanted = {p[2:] if p.startswith("./") else p for p in changed}
    found: List[str] = []
    if not wanted or not kits_dir.is_dir():
        return found
    for kit_dir in sorted(p for p in kits_dir.iterdir() if p.is_dir()):
        if kit_dir.name.startswith("_"):
            continue
        manifest_path = kit_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "available":
            continue
        srcs = {str(a.get("src", "")) for a in manifest.get("artifacts") or []}
        if srcs & wanted:
            found.append(kit_dir.name)
    return found


def main(argv: List[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    for kit in affected_kits(args, ROOT / "block_store" / "kits"):
        print(kit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
