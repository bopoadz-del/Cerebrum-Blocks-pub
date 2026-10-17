#!/usr/bin/env python3
"""Give a registry block the adapter it is missing — and nothing else.

``regenerate_safe_adapters.py`` rewrites and re-signs EVERY entry in
``block_registry``. That is the right tool for a format migration and the wrong
one here: it would clobber hand-written adapters (``reference_corpus`` has one
that is not the boilerplate) and re-sign 234 manifests to fix 16.

This writes the SAME canonical adapter — imported from that script, so the
boilerplate has one source of truth and cannot drift — into only the folders
that have a ``block.json`` and no ``block.py``, and signs only those.

WHY IT IS NEEDED
----------------
A registry folder without ``block.py`` fails the Store's own ``BlockValidator``
with ``block.py not found`` and is excluded from ``_BLOCK_DEFS``, so the Store
advertises a block it will not serve. Twenty entries were in that state and a
live Factory build stopped on one of them (``action_contract``).

An adapter is only written for a block that has a RUNTIME MAPPING in
``app/blocks/__init__.py``. Without one, ``get_block(<id>)`` inside the adapter
resolves to nothing, and shipping an adapter around nothing is the failure this
repo refused after the always-ok estate blocks. Those are reported, not written.

USAGE
-----
    python scripts/add_missing_adapters.py --key <path-to-private-key.pem>
    python scripts/add_missing_adapters.py --dry-run     # no key needed

The key is never read in ``--dry-run``. It is read only by the repo's own
``_load_private_key`` and never logged.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "block_registry"
SKIP = {"__pycache__", "Dockerfile.base"}


def _regenerator():
    """The canonical adapter template and signer, imported not copied."""
    spec = importlib.util.spec_from_file_location(
        "regenerate_safe_adapters", ROOT / "scripts" / "regenerate_safe_adapters.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runtime_mapped() -> set:
    """Block ids the Store runtime registry can actually resolve."""
    sys.path.insert(0, str(ROOT))
    import app.blocks as blocks

    return set(blocks._GENERIC_BLOCK_DEFS) | set(blocks._EXTENDED_BLOCK_DEFS)


def survey() -> Tuple[List[str], List[str]]:
    """(needs an adapter and can have one, needs one but has no runtime)."""
    mapped = _runtime_mapped()
    writable, orphaned = [], []
    for folder in sorted(REGISTRY.iterdir()):
        if not folder.is_dir() or folder.name in SKIP:
            continue
        if not (folder / "block.json").is_file() or (folder / "block.py").is_file():
            continue
        (writable if folder.name in mapped else orphaned).append(folder.name)
    return writable, orphaned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--key", type=Path, help="Path to the publisher Ed25519 PEM")
    parser.add_argument("--publisher", default="cerebrum_platform")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be written; reads no key")
    args = parser.parse_args()

    writable, orphaned = survey()

    print(f"missing an adapter AND runtime-mapped -> will be written: {len(writable)}")
    for name in writable:
        print(f"    {name}")
    print(f"missing an adapter and NOT runtime-mapped -> refused: {len(orphaned)}")
    for name in orphaned:
        print(f"    {name}  (get_block would resolve to nothing)")

    if args.dry_run:
        print("\ndry run: nothing written, no key read")
        return 0
    if not writable:
        print("\nnothing to do")
        return 0
    if not args.key:
        print("\nERROR: --key is required unless --dry-run", file=sys.stderr)
        return 2

    regen = _regenerator()
    private_key = regen._load_private_key(args.key)
    for name in writable:
        regen.regenerate_adapter(REGISTRY / name, args.publisher, private_key)
        print(f"[OK] wrote and signed {name}/block.py")
    print(f"\nwrote and signed {len(writable)} adapters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
