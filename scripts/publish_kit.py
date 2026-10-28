#!/usr/bin/env python3
"""Publish a domain container kit to the Cerebrum Block Store.

TWO MODES, AND WHY THE DEFAULT IS MIRROR
----------------------------------------
``scaffold`` generates a manifest from the standard template -- the right
thing for a brand-new kit, and the only thing this script used to do.

``mirror`` reads the manifest the kit author already wrote and copies every
artifact it declares into ``bundle/``. This is the mode the store actually
needs, because ``container_kit_store.install_kit`` reads install artifacts
from ``bundle/`` and nowhere else.

The default is mirror-when-a-manifest-exists, and scaffold refuses to
overwrite one without ``--regenerate``. That is not politeness. The template
emits a fixed 14-artifact list; ``automotive`` had been hand-extended to 18
by #64 (source_manifest.json, schemas/, prompts/, evaluation/). Running the
old script against it would have silently reverted the manifest to the
template and republished a kit stripped of everything that made it a RAG kit.

WHAT PUBLISH REFUSES
--------------------
After copying, every declared artifact must exist in ``bundle/`` or the
publish fails. ``automotive`` shipped 14 of the 18 it declared while the
store still listed it ``available``, and install raised ContainerKitError at
the last step. Declared-but-absent is now a publish-time error rather than an
install-time surprise.

WHEN THE SOURCE IS GONE
-----------------------
``construction`` and ``insurance`` were published from The_Fork, and most of
what they declare is authored in neither this repo nor the current Fork
checkout -- their ``bundle/`` is the only surviving copy. A strict mirror can
only refuse them, which would freeze their vendored platform code forever.
``--refresh`` copies every artifact whose source it can find, reports the
orphans, and still exits non-zero.

Usage:
    python scripts/publish_kit.py --domain automotive             # mirror
    python scripts/publish_kit.py --domain automotive --check     # verify only
    python scripts/publish_kit.py --domain automotive --dry-run
    python scripts/publish_kit.py --domain medical --scaffold     # new kit
    python scripts/publish_kit.py --domain insurance --refresh    # sources partly gone
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KITS_DIR = PROJECT_ROOT / "block_store" / "kits"

# Human-readable titles for each kit.
_KIT_TITLES = {
    "construction": "Construction AEC Suite",
    "medical": "Medical & Healthcare Suite",
    "hotel_management": "Hotel Management & Hospitality Suite",
    "finance": "Finance & Investment Suite",
    "legal": "Legal & Contracts Suite",
    "retail": "Retail & E-commerce Suite",
    "pharma": "Pharmaceuticals & Life Sciences Suite",
    "insurance": "Insurance & Risk Suite",
    "supply_chain": "Supply Chain & Logistics Suite",
    "real_estate": "Real Estate & Property Suite",
    "automotive": "Automotive & Mobility Suite",
    "education": "Education & E-learning Suite",
    "agriculture": "Agriculture & AgriTech Suite",
    "hr": "Human Resources & Recruitment Suite",
    "manufacturing": "Manufacturing & Industry 4.0 Suite",
    "aviation": "Aviation & Aerospace Suite",
    "oil_gas": "Oil & Gas Suite",
}

# Domains that need a non-standard Pascal-case class name.
_CLASS_NAME_OVERRIDES = {
    "hr": "HR",
}

# Domains whose source filenames don't follow the default pattern.
_FILE_NAME_OVERRIDES = {
    "hotel_management": {
        "block": "hotel",
        "knowledge": "hotel",
        "types": "hotel",
    },
}


def repo_identity(env: Optional[dict] = None, checkout: Optional[Path] = None) -> dict[str, str]:
    """Owner and repo URL of the checkout this script lives in.

    Read from GITHUB_REPOSITORY (set by Actions) or else the git remote
    ``origin`` of this checkout. Nothing is assumed: no source, no identity.
    """
    env = os.environ if env is None else env
    slug = (env.get("GITHUB_REPOSITORY") or "").strip()
    if not slug:
        try:
            url = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                cwd=checkout or Path(__file__).resolve().parent, capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            url = ""
        m = re.search(r"github\.com[:/]+([^/\s]+/[^/\s]+?)(?:\.git)?/?$", url)
        slug = m.group(1) if m else ""
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", slug):
        raise RuntimeError(
            "cannot determine the repository owner: set GITHUB_REPOSITORY=owner/repo "
            "or run from a checkout whose origin is a GitHub URL"
        )
    owner = slug.split("/", 1)[0]
    return {"owner": owner, "repo": f"https://github.com/{slug}"}


def _file_prefix(domain: str, component: str) -> str:
    return _FILE_NAME_OVERRIDES.get(domain, {}).get(component, domain)


def _pascal_name(domain: str) -> str:
    """Convert domain id to a PascalCase prefix (e.g. oil_gas -> OilGas, hr -> HR)."""
    if domain in _CLASS_NAME_OVERRIDES:
        return _CLASS_NAME_OVERRIDES[domain]
    return "".join(part.title() for part in domain.split("_"))


def _artifact(src: str) -> dict[str, str]:
    return {"src": src, "dest": src}


def _build_manifest(domain: str, identity: Optional[dict] = None) -> dict[str, object]:
    identity = identity or repo_identity()
    pascal = _pascal_name(domain)
    container_class = f"app.containers.{domain}.{pascal}Container"
    block_name = f"{domain}_v2"

    title = _KIT_TITLES.get(domain, f"{pascal} Suite")
    description = (
        f"{title}: typed document analysis, entity extraction, metrics, "
        f"compliance checks, and risk scoring for the {domain.replace('_', ' ')} domain."
    )

    # Source files that make up the full domain kit.
    block_prefix = _file_prefix(domain, "block")
    knowledge_prefix = _file_prefix(domain, "knowledge")
    types_prefix = _file_prefix(domain, "types")
    source_files = [
        f"app/containers/{domain}.py",
        f"app/blocks/{block_prefix}_v2.py",
        f"app/core/{knowledge_prefix}_knowledge.py",
        f"app/core/{types_prefix}_types.py",
    ]

    # Shared infrastructure required by all v2 domain blocks.
    shared_files = [
        "app/core/confidence.py",
        "app/core/schema_registry.py",
        "app/core/domain_block_v2.py",
        "app/core/metric_utils.py",
        "app/core/typed_block.py",
        "app/core/universal_base.py",
        "app/containers/base.py",
        "app/core/sandbox.py",
        "app/prompts/codegen_system.py",
        "app/blocks/formula_executor_v2.py",
    ]

    artifacts = [_artifact(path) for path in source_files + shared_files]

    return {
        "id": domain,
        "name": title,
        "version": "1.0.0",
        "description": description,
        "status": "available",
        "author": identity["owner"],
        "tags": ["domain", "container", domain],
        "source": {
            "repo": identity["repo"],
            "ref": "main",
            "publish_script": "scripts/publish_kit.py",
        },
        "container": {
            "class": container_class,
            "default_chat_prompt": None,
        },
        "blocks": [
            "pdf",
            "ocr",
            "chat",
            "image",
            block_name,
            "formula_executor_v2",
        ],
        "prompts": [],
        "data": [],
        "core_modules": [
            f"app/core/{knowledge_prefix}_knowledge.py",
            f"app/core/{types_prefix}_types.py",
            "app/core/confidence.py",
            "app/core/schema_registry.py",
            "app/core/domain_block_v2.py",
            "app/core/metric_utils.py",
            "app/core/typed_block.py",
            "app/core/universal_base.py",
            "app/containers/base.py",
            "app/core/sandbox.py",
            "app/prompts/codegen_system.py",
        ],
        "artifacts": artifacts,
        "price_cents": 0,
        "install_requires": {
            "min_platform_version": "2.0.0",
            "python": ">=3.10",
        },
    }


# -- publishing ------------------------------------------------------------


def resolve_source(kit_dir: Path, rel: str) -> Optional[Path]:
    """Where an artifact is authored.

    Kit-authored content (``schemas/``, ``prompts/``, ``source_manifest.json``)
    lives at the kit root; shared platform code (``app/core/sandbox.py`` and
    friends) lives at the repo root. The kit root wins, so a kit can carry its
    own copy of a shared file without editing the repo.
    """
    for candidate in (kit_dir / rel, PROJECT_ROOT / rel):
        if candidate.exists():
            return candidate
    return None


def copy_artifact(src: Path, dest: Path) -> None:
    """Copy a file or a whole directory.

    An artifact may be a directory (``schemas/``, ``prompts/``).
    ``shutil.copy2`` raises IsADirectoryError on those, so the kind is checked
    rather than assumed -- three of automotive's artifacts are directories.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(
            src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
    else:
        shutil.copy2(src, dest)


def missing_from_bundle(bundle_dir: Path, artifacts: List[Any]) -> List[str]:
    """Declared artifacts absent from the bundle. Empty means installable.

    This is the same invariant ``tests/test_kit_bundle_completeness.py``
    asserts in CI and ``container_kit_store.install_kit`` enforces at install.
    Checked here too so a bad publish fails at the keyboard of the person who
    caused it, not in someone else's install.
    """
    return [
        item["src"] for item in artifacts if not (bundle_dir / item["src"]).exists()
    ]


def composition_audit(domain: str, kit_dir: Path) -> int:
    """The publish gate from #69, reachable from BOTH publish paths.

    CI catches a bad manifest on the next push; this catches it before the kit
    is on the shelf, which is the point at which a consumer could install it.
    Reported, not silently swallowed -- and it runs after the write so the
    findings name the manifest as published.

    It lived inside ``scaffold()`` alone after #69 and #74 merged, which meant
    it stopped running on ``mirror`` -- the default path, and the one every
    already-authored kit takes. A gate that only guards the branch nobody
    takes is not a gate.
    """
    # Import by path, not by luck. Running this file as a script puts
    # scripts/ on sys.path implicitly; importing it as a module (tests, or any
    # caller that wants publish_kit's helpers) does not, and the audit then
    # raised ModuleNotFoundError from inside the publish path.
    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))

    from audit_kit_composition import (
        MODULES_DIR,
        REGISTRY_DIR,
        _dirs,
        _modules,
        audit_kit,
        load_known,
    )

    known = _dirs(REGISTRY_DIR) | _modules(MODULES_DIR)
    # Same registration contract as CI: a gap that is declared in
    # KNOWN_KIT_GAPS.md does not block, or publishing any already-registered
    # kit would fail while CI passes -- two gates disagreeing about the same
    # manifest is worse than either one alone.
    registered = load_known()
    findings = [
        (code, detail)
        for code, detail in audit_kit(domain, str(kit_dir.parent), known)
        if f"{domain} :: {code}" not in registered
    ]
    if findings:
        print(f"\nCOMPOSITION FINDINGS for '{domain}':")
        for code, detail in findings:
            print(f"  {code}: {detail}")
        print(
            "Kit is on the shelf but does not pass the composition audit. "
            f"Fix it, or register it in KNOWN_KIT_GAPS.md as '{domain} :: <code>'."
        )
        return 1
    print("Composition audit: clean.")
    return 0


def stamp_identity(manifest_path: Path, identity: Optional[dict] = None) -> dict:
    """Regenerate an authored manifest's author and source.repo from the
    repository config (repo_identity), leaving every other field as authored."""
    identity = identity or repo_identity()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["author"] = identity["owner"]
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    manifest["source"] = {"repo": identity["repo"], **{k: v for k, v in source.items() if k != "repo"}}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def mirror(
    kit_dir: Path,
    manifest_path: Path,
    dry_run: bool,
    check_only: bool,
    refresh: bool = False,
) -> int:
    """Copy declared artifacts into ``bundle/``.

    ``refresh`` exists for a kit whose sources are partly unreachable. No
    kit needs it today: tests/test_kit_declared_files_exist.py requires every
    declared artifact to resolve, so an orphan fails CI before it gets here.

    So ``refresh`` copies every artifact whose source it can find and reports
    the orphans, still exiting non-zero. The kit gets current shared code; no
    one is told the publish succeeded.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest.get("artifacts") or []
    bundle_dir = kit_dir / "bundle"
    kit_id = manifest.get("id", kit_dir.name)

    if not artifacts:
        print(f"'{kit_id}' declares no artifacts; nothing to mirror.")
        return 0

    if check_only:
        missing = missing_from_bundle(bundle_dir, artifacts)
        if missing:
            print(
                f"INCOMPLETE '{kit_id}': {len(missing)} of {len(artifacts)} declared "
                f"artifacts are absent from bundle/:",
                file=sys.stderr,
            )
            for item in missing:
                print(f"  - {item}", file=sys.stderr)
            return 1
        print(
            f"'{kit_id}': all {len(artifacts)} declared artifacts present in bundle/."
        )
        return 0

    unresolved: List[str] = []
    plan = []
    for item in artifacts:
        src = resolve_source(kit_dir, item["src"])
        if src is None:
            unresolved.append(item["src"])
        else:
            plan.append((src, bundle_dir / item["src"]))

    if unresolved and not refresh:
        print(
            f"Cannot mirror '{kit_id}': {len(unresolved)} declared artifact(s) are "
            f"authored nowhere -- not at the kit root, not at the repo root:",
            file=sys.stderr,
        )
        for item in unresolved:
            print(f"  - {item}", file=sys.stderr)
        print(
            "Write them, or remove them from the manifest. Publishing a kit that "
            "declares what does not exist is exactly what broke automotive.",
            file=sys.stderr,
        )
        return 1

    if dry_run:
        for src, dest in plan:
            print(f"[dry-run] {'dir ' if src.is_dir() else 'file'} {src} -> {dest}")
        return 0

    for src, dest in plan:
        copy_artifact(src, dest)

    if unresolved:
        print(f"Refreshed '{kit_id}': {len(plan)} of {len(artifacts)} artifacts.")
        print(
            f"\n{len(unresolved)} declared artifact(s) have no reachable source; the "
            f"copy already in bundle/ is all that exists of them:",
            file=sys.stderr,
        )
        for item in unresolved:
            print(f"  - {item}", file=sys.stderr)
        print(
            "This kit cannot be rebuilt from source. Recorded in "
            "KNOWN_INCOMPLETE.md; --refresh keeps its shared code current "
            "without pretending the publish was complete.",
            file=sys.stderr,
        )
        return 1

    missing = missing_from_bundle(bundle_dir, artifacts)
    if missing:
        print(
            f"Publish FAILED for '{kit_id}': still missing after copy: {missing}",
            file=sys.stderr,
        )
        return 1

    print(f"Mirrored '{kit_id}': {len(plan)} artifacts -> {bundle_dir}")
    print(f"Completeness: {len(artifacts)}/{len(artifacts)} declared artifacts present.")
    return composition_audit(kit_id, kit_dir)


def scaffold(
    kit_dir: Path, manifest_path: Path, domain: str, dry_run: bool, regenerate: bool
) -> int:
    if manifest_path.exists() and not regenerate:
        print(
            f"'{domain}' already has an authored manifest at {manifest_path}.",
            file=sys.stderr,
        )
        print(
            "Refusing to overwrite it with the standard template. The template "
            "emits a fixed artifact list and would drop anything hand-added -- "
            "this is how automotive's RAG artifacts would have been lost. Publish "
            "it as authored (default), or pass --regenerate to insist.",
            file=sys.stderr,
        )
        return 1

    manifest = _build_manifest(domain)
    artifacts = manifest["artifacts"]
    bundle_dir = kit_dir / "bundle"

    absent = [i["src"] for i in artifacts if not (PROJECT_ROOT / i["src"]).exists()]
    if absent:
        print(f"Missing source files for '{domain}':", file=sys.stderr)
        for item in absent:
            print(f"  - {item}", file=sys.stderr)
        return 1

    if dry_run:
        print(f"[dry-run] would write {manifest_path}")
        for item in artifacts:
            print(f"[dry-run] would copy {item['src']} -> {bundle_dir / item['src']}")
        return 0

    kit_dir.mkdir(parents=True, exist_ok=True)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    for item in artifacts:
        copy_artifact(PROJECT_ROOT / item["src"], bundle_dir / item["src"])

    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")

    missing = missing_from_bundle(bundle_dir, artifacts)
    if missing:
        print(
            f"Publish FAILED for '{domain}': still missing after copy: {missing}",
            file=sys.stderr,
        )
        return 1

    print(f"Scaffolded '{domain}': {len(artifacts)} artifacts -> {bundle_dir}")
    print(f"Manifest written: {manifest_path}")

    return composition_audit(domain, kit_dir)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish a domain kit to the Cerebrum Block Store."
    )
    parser.add_argument("--domain", required=True, help="Kit id (e.g. automotive)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions only")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify bundle completeness without copying anything",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--mirror",
        action="store_true",
        help="Publish the manifest as authored (the default when one exists)",
    )
    mode.add_argument(
        "--scaffold",
        action="store_true",
        help="Generate a manifest from the standard template (new kits)",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Allow --scaffold to overwrite an authored manifest",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Copy artifacts whose source exists and report the rest, for kits "
             "whose sources are no longer reachable (construction, insurance)",
    )
    parser.add_argument(
        "--stamp-identity",
        action="store_true",
        help="Regenerate the manifest's author and source.repo from the repository "
             "config (GITHUB_REPOSITORY or git remote origin)",
    )
    args = parser.parse_args()

    domain = args.domain.strip().lower()
    kit_dir = KITS_DIR / domain
    manifest_path = kit_dir / "manifest.json"

    if args.scaffold:
        if args.check:
            print(
                "--check inspects an authored manifest; drop --scaffold to use it.",
                file=sys.stderr,
            )
            return 2
        return scaffold(kit_dir, manifest_path, domain, args.dry_run, args.regenerate)

    if not manifest_path.exists():
        if args.mirror or args.check:
            print(
                f"No manifest at {manifest_path}; nothing to mirror. "
                f"Use --scaffold to create one.",
                file=sys.stderr,
            )
            return 1
        print(f"No manifest for '{domain}' -- scaffolding a new kit.")
        return scaffold(kit_dir, manifest_path, domain, args.dry_run, args.regenerate)

    if args.stamp_identity:
        manifest = stamp_identity(manifest_path)
        print(f"Stamped {manifest_path}: author={manifest['author']} repo={manifest['source']['repo']}")
        if args.check:
            return mirror(kit_dir, manifest_path, args.dry_run, True, args.refresh)
        return 0

    return mirror(kit_dir, manifest_path, args.dry_run, args.check, args.refresh)


if __name__ == "__main__":
    raise SystemExit(main())
