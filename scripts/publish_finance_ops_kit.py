#!/usr/bin/env python3
"""Regenerate the checked-in FinanceOps kit bundle from its manifest."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KIT_DIR = PROJECT_ROOT / "block_store" / "kits" / "finance_ops"
MANIFEST_PATH = KIT_DIR / "manifest.json"
BUNDLE_DIR = KIT_DIR / "bundle"


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish FinanceOps Store kit")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("id") != "finance_ops":
        print("FinanceOps manifest id mismatch", file=sys.stderr)
        return 1
    artifacts = manifest.get("artifacts") or []
    missing = [item["src"] for item in artifacts if not (PROJECT_ROOT / item["src"]).is_file()]
    if missing:
        print("Missing FinanceOps source artifacts:", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        return 1
    for item in artifacts:
        src = PROJECT_ROOT / item["src"]
        dest = BUNDLE_DIR / item["src"]
        if args.dry_run:
            print(f"[dry-run] {src.relative_to(PROJECT_ROOT)} -> {dest.relative_to(PROJECT_ROOT)}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    print(f"FinanceOps kit bundle {'validated' if args.dry_run else 'published'}: {len(artifacts)} artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
