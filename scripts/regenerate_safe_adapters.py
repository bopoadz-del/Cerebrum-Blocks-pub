#!/usr/bin/env python3
"""Regenerate block_registry adapters to pass the Phase-3 validation gate.

Old adapters imported ``sys`` and ``BLOCK_REGISTRY`` directly. This script
rewrites every ``block_registry/*/block.py`` to use the capability-safe
``app.blocks.get_block`` helper, then re-signs each block manifest with the
configured publisher key.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "block_registry"
SKIP = {"__pycache__", "Dockerfile.base"}

ADAPTER_TEMPLATE = '''#!/usr/bin/env python3
"""
Auto-generated adapter for Cerebrum block: {block_id}
Wraps app.blocks.{block_id} into a synchronous run() function.
"""

import asyncio
from app.blocks import get_block


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """
    Execute the {block_id} block.
    Accepts keyword args matching the block's inputs/params.
    Returns the standardized block result payload.
    """
    block_cls = get_block("{block_id}")
    instance = block_cls()

    input_data = kwargs.get("input", kwargs)
    params = {{k: v for k, v in kwargs.items() if k != "input"}}

    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") == "error":
        inner = envelope.get("result", {{}})
        message = inner.get("error") if isinstance(inner, dict) else str(inner)
        raise RuntimeError(message or "{block_id} block failed")

    return envelope.get("result", envelope)
'''


def _load_private_key(path: Path):
    sys.path.insert(0, str(ROOT))
    from app.core.publisher_registry import _load_private_key as load

    return load(path)


def _sign_block(block_path: Path, publisher_id: str, private_key) -> dict:
    sys.path.insert(0, str(ROOT))
    from app.core.publisher_registry import BlockSigner

    return BlockSigner.sign_block(
        block_path=block_path,
        publisher_id=publisher_id,
        private_key=private_key,
    )


def _read_block_id(block_path: Path) -> Optional[str]:
    manifest_path = block_path / "block.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8")).get("id")
    except (json.JSONDecodeError, OSError):
        return None


def regenerate_adapter(block_path: Path, publisher_id: str, private_key) -> bool:
    block_id = _read_block_id(block_path)
    if block_id is None:
        print(f"[SKIP] no readable block.json in {block_path}")
        return False

    adapter_path = block_path / "block.py"
    adapter_path.write_text(
        ADAPTER_TEMPLATE.format(block_id=block_id),
        encoding="utf-8",
    )

    _sign_block(block_path, publisher_id, private_key)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate safe adapters and re-sign block_registry entries."
    )
    parser.add_argument(
        "--publisher",
        default="cerebrum_platform",
        help="Publisher ID to sign with",
    )
    parser.add_argument(
        "--key",
        type=Path,
        default=ROOT / "data" / "publishers" / "cerebrum_platform.key",
        help="Path to publisher Ed25519 private key",
    )
    args = parser.parse_args()

    private_key = _load_private_key(args.key)

    updated = 0
    for block_dir in sorted(REGISTRY.iterdir()):
        if not block_dir.is_dir() or block_dir.name in SKIP:
            continue
        if regenerate_adapter(block_dir, args.publisher, private_key):
            print(f"[OK] regenerated {block_dir.name}/block.py")
            updated += 1

    print(f"Regenerated and signed {updated} adapters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
