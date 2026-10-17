#!/usr/bin/env python3
"""Publish the insurance distribution kit bundle.

Copies the insurance v2/distribution block implementations from ``app/blocks``
into ``block_store/kits/insurance/bundle/app/blocks`` and verifies bundled
data, knowledge, and playbook resources that live only inside the kit bundle.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KIT_ID = "insurance"
KIT_VERSION = "2.0.0"
KIT_DIR = PROJECT_ROOT / "block_store" / "kits" / KIT_ID
MANIFEST_PATH = KIT_DIR / "manifest.json"
BUNDLE_DIR = KIT_DIR / "bundle"

INSURANCE_BLOCKS = [
    "insurance_v2",
    "formula_executor_v2",
    "agency_hierarchy",
    "producer_record",
    "agency_commission_engine",
    "channel_router",
    "attrition_scorer",
    "incentive_targeting",
    "hkia_gn16_rules",
    "bordereaux_ingest",
    "distribution_analytics",
]

ROOT_ARTIFACTS = [
    "app/containers/insurance.py",
    "app/core/insurance_knowledge.py",
    "app/core/insurance_types.py",
    "app/core/confidence.py",
    "app/core/schema_registry.py",
    "app/core/domain_block_v2.py",
    "app/core/metric_utils.py",
    "app/core/typed_block.py",
    "app/core/universal_base.py",
    "app/containers/base.py",
    "app/core/sandbox.py",
    "app/prompts/codegen_system.py",
    *[f"app/blocks/{block_id}.py" for block_id in INSURANCE_BLOCKS],
]

BUNDLE_RESOURCES = [
    "app/data/gn16_ruleset.json",
    "app/knowledge/hkia_gn16_corpus.json",
    "app/playbooks/distribution.json",
    "app/playbooks/compensation.json",
    "app/playbooks/compliance.json",
    "app/playbooks/analytics.json",
]


def _load_manifest() -> dict[str, object]:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Kit manifest missing: {MANIFEST_PATH}")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _write_manifest(manifest: dict[str, object]) -> None:
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _ensure_manifest_v2(manifest: dict[str, object], *, dry_run: bool) -> bool:
    changed = False
    if manifest.get("version") != KIT_VERSION:
        manifest["version"] = KIT_VERSION
        changed = True

    source = manifest.setdefault("source", {})
    if isinstance(source, dict) and source.get("publish_script") != "scripts/publish_insurance_kit.py":
        source["publish_script"] = "scripts/publish_insurance_kit.py"
        changed = True

    if changed:
        if dry_run:
            print(f"[dry-run] would update manifest version/source at {MANIFEST_PATH}")
        else:
            _write_manifest(manifest)
            print(f"updated manifest version/source: {MANIFEST_PATH}")

    return changed


def _copy_root_artifacts(*, dry_run: bool) -> tuple[int, list[str]]:
    copied = 0
    missing: list[str] = []

    for rel_path in ROOT_ARTIFACTS:
        src = PROJECT_ROOT / rel_path
        dest = BUNDLE_DIR / rel_path

        if not src.exists():
            missing.append(rel_path)
            continue

        if dry_run:
            print(f"[dry-run] would copy {src} -> {dest}")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            print(f"copied {rel_path}")
        copied += 1

    return copied, missing


def _verify_bundle_resources() -> list[str]:
    return [rel_path for rel_path in BUNDLE_RESOURCES if not (BUNDLE_DIR / rel_path).exists()]


def _verify_manifest_artifacts(manifest: dict[str, object]) -> list[str]:
    missing: list[str] = []
    for item in manifest.get("artifacts", []):
        if not isinstance(item, dict):
            continue
        dest = str(item.get("dest") or item.get("src") or "")
        if dest and not (BUNDLE_DIR / dest).exists():
            missing.append(dest)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish insurance kit v2 bundle")
    parser.add_argument("--dry-run", action="store_true", help="Print actions only")
    args = parser.parse_args()

    try:
        manifest = _load_manifest()
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error loading manifest: {exc}", file=sys.stderr)
        return 1

    if manifest.get("id") != KIT_ID:
        print(f"Unexpected manifest id: {manifest.get('id')!r}", file=sys.stderr)
        return 1

    _ensure_manifest_v2(manifest, dry_run=args.dry_run)

    copied, missing_sources = _copy_root_artifacts(dry_run=args.dry_run)
    missing_resources = _verify_bundle_resources()

    if missing_sources:
        print("\nMissing root artifacts:", file=sys.stderr)
        for rel_path in missing_sources:
            print(f"  - {rel_path}", file=sys.stderr)

    if missing_resources:
        print("\nMissing bundle data/knowledge/playbooks:", file=sys.stderr)
        for rel_path in missing_resources:
            print(f"  - {rel_path}", file=sys.stderr)

    missing_manifest_artifacts: list[str] = []
    if not args.dry_run and not missing_sources and not missing_resources:
        refreshed_manifest = _load_manifest()
        missing_manifest_artifacts = _verify_manifest_artifacts(refreshed_manifest)
        if missing_manifest_artifacts:
            print("\nMissing manifest artifacts in bundle:", file=sys.stderr)
            for rel_path in missing_manifest_artifacts:
                print(f"  - {rel_path}", file=sys.stderr)

    verb = "Would copy" if args.dry_run else "Copied"
    print(f"\n{verb} {copied}/{len(ROOT_ARTIFACTS)} root artifacts")
    print(f"bundle_resources_present={len(BUNDLE_RESOURCES) - len(missing_resources)}/{len(BUNDLE_RESOURCES)}")
    print(f"manifest_version={KIT_VERSION}")
    print(f"blocks_registered={len(manifest.get('blocks') or [])}")

    if missing_sources or missing_resources or missing_manifest_artifacts:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
