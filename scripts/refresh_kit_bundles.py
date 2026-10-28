#!/usr/bin/env python3
"""Refresh the vendored bundle of every kit that mirrors a re-signed block.

WHY THIS EXISTS
---------------
``scripts/rotate_publisher_key.py`` rewrites ``signature`` and ``digests`` in
every ``block_registry/*/block.json`` it re-signs. Some kits vendor those same
``block.json`` files into ``block_store/kits/<kit>/bundle/`` as declared
artifacts, so a re-sign makes their bundled copies drift from the registry
sources and ``tests/test_kit_bundle_freshness.py`` turns red on the rotation
PR.

The fix is to re-mirror exactly the kits that are affected -- no more, no less.
Which kits those are is read FROM DATA: a kit is affected iff its
``manifest.json`` declares an ``artifacts[].src`` that is one of the re-signed
``block.json`` paths. No kit name is hardcoded here or in the workflow; add a
kit that mirrors a re-signed block tomorrow and it is picked up with no change
to this file. A kit that mirrors none of them is left untouched.

The mirror itself is the existing, unchanged publish path
(``scripts/publish_kit.py --domain <kit> --mirror``), so this script only
decides *which* kits to mirror and runs it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _norm(path: str) -> str:
    return str(path).replace("\\", "/").strip()


def affected_kits(kits_root: Path, resigned_blocks: Iterable[str]) -> list[str]:
    """Kit ids that declare an artifact whose src is a re-signed block path.

    ``resigned_blocks`` are repo-relative ``block_registry/<name>/block.json``
    paths. Only kits whose manifest ``status`` is ``available`` and which
    actually declare one of those paths are returned -- derived purely from
    the manifests, so no kit name is ever assumed.
    """
    resigned = {_norm(p) for p in resigned_blocks if _norm(p)}
    if not resigned:
        return []
    hits: list[str] = []
    for kit_dir in sorted(p for p in kits_root.iterdir() if p.is_dir()):
        if kit_dir.name.startswith("_"):
            continue
        manifest_path = kit_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "available":
            continue
        declared = {_norm(a.get("src", "")) for a in (manifest.get("artifacts") or [])}
        if declared & resigned:
            hits.append(manifest.get("id", kit_dir.name))
    return hits


def _run_publish_kit(kit_id: str, root: Path) -> None:
    """Run the existing publish_kit mirror for one kit; raise if it fails."""
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "publish_kit.py"), "--domain", kit_id, "--mirror"],
        cwd=str(root),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"publish_kit.py --domain {kit_id} --mirror failed "
            f"(exit {result.returncode}); bundle not refreshed"
        )


def refresh(
    root: Path,
    resigned_blocks: Iterable[str],
    mirror: Callable[[str, Path], None] = _run_publish_kit,
) -> list[str]:
    """Mirror every affected kit; return the kit ids that were refreshed."""
    kits = affected_kits(root / "block_store" / "kits", resigned_blocks)
    for kit_id in kits:
        mirror(kit_id, root)
    return kits


def _changed_block_manifests(root: Path) -> list[str]:
    """Re-signed block.json paths, from the working-tree diff under block_registry."""
    out = subprocess.run(
        ["git", "diff", "--name-only", "--", "block_registry"],
        cwd=str(root), capture_output=True, text=True,
    ).stdout
    return [
        _norm(line)
        for line in out.splitlines()
        if _norm(line).endswith("/block.json")
    ]


def main(argv: list[str] | None = None, root: Path = PROJECT_ROOT) -> int:
    root = Path(root).resolve()
    argv = sys.argv[1:] if argv is None else argv
    resigned = [a for a in argv] if argv else _changed_block_manifests(root)
    if not resigned:
        print("no re-signed block.json paths; no kit bundles to refresh")
        return 0
    refreshed = refresh(root, resigned)
    if refreshed:
        print(f"refreshed bundle(s) for affected kit(s): {', '.join(refreshed)}")
    else:
        print("no available kit mirrors any re-signed block; nothing to refresh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
