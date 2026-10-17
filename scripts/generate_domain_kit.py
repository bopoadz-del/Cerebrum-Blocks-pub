#!/usr/bin/env python3
"""Generate domain kit skeletons under block_store/kits/{domain}/.

Usage:
    python scripts/generate_domain_kit.py medical
    python scripts/generate_domain_kit.py --all
    python scripts/generate_domain_kit.py --list
    python scripts/generate_domain_kit.py law --coming-soon
    python scripts/generate_domain_kit.py medical --force
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KITS_DIR = PROJECT_ROOT / "block_store" / "kits"
TEMPLATE_DIR = KITS_DIR / "_template"

SKIP_KITS = frozenset({"construction", "_template"})

DOMAIN_CATALOG: dict[str, dict[str, Any]] = {
    "medical": {
        "name": "Medical & Healthcare Suite",
        "description": "Clinical workflows, patient records intelligence, and healthcare compliance blocks.",
        "tags": ["domain", "container", "medical", "healthcare"],
    },
    "law": {
        "name": "Law & Legal Practice Suite",
        "description": "Contract analysis, case research, and legal document intelligence blocks.",
        "tags": ["domain", "container", "law", "legal"],
    },
    "banking": {
        "name": "Banking Operations Suite",
        "description": "Retail and commercial banking workflows, KYC, and regulatory compliance blocks.",
        "tags": ["domain", "container", "banking", "finance"],
    },
    "finance": {
        "name": "Finance & Investment Suite",
        "description": "Portfolio analysis, financial modeling, and investment research blocks.",
        "tags": ["domain", "container", "finance", "investment"],
    },
    "security": {
        "name": "Security & Surveillance Suite",
        "description": "Physical security, access control, and threat monitoring blocks.",
        "tags": ["domain", "container", "security", "surveillance"],
    },
    "maintenance": {
        "name": "Maintenance & Facilities Suite",
        "description": "Work orders, asset lifecycle, and preventive maintenance blocks.",
        "tags": ["domain", "container", "maintenance", "facilities"],
    },
    "hotel_management": {
        "name": "Hotel Management Suite",
        "description": "Guest services, reservations, housekeeping, and hospitality operations blocks.",
        "tags": ["domain", "container", "hospitality", "hotel"],
    },
}

SKELETON_FILES = [
    "container.py",
    "knowledge.py",
    "types.py",
    "prompts/{domain}_expert.txt",
    "prompts/{domain}_workflow.md",
    "blocks/README.md",
    # KERNEL_DEFAULTS 1.3: a block and the three tests it must ship with.
    # The template renders both without edits -- see
    # tests/core/test_template_three_tests.py, which generates a throwaway
    # kit, runs the rendered tests, and deletes it.
    "blocks/{domain}_block.py",
    "tests/test_{domain}_block.py",
]

#: Template paths whose FILENAME carries the domain. On disk the template is
#: ``prompts/{{domain}}_expert.txt``; the rendered kit gets
#: ``prompts/dental_expert.txt``. Both halves of that mapping live here.
_DOMAIN_NAMED_DIRS = ("prompts/", "blocks/", "tests/")

CONNECTOR_STUBS: dict[str, list[str]] = {
    "medical": [
        "blocks/medical_ehr_connector.py",
        "blocks/clinical_trigger.py",
    ],
    "hotel_management": [
        "blocks/opera_connector.py",
        "blocks/video_metadata_ingest.py",
        "blocks/hotel_trigger.py",
    ],
}


def _pascal_case(domain_id: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[_-]+", domain_id) if part)


def _render(template_text: str, context: dict[str, Any]) -> str:
    rendered = template_text
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered


def _load_template(rel_path: str) -> str:
    path = TEMPLATE_DIR / rel_path
    if not path.is_file():
        raise FileNotFoundError(f"Template missing: {path}")
    return path.read_text(encoding="utf-8")


def _build_context(domain_id: str, *, status: str) -> dict[str, Any]:
    meta = DOMAIN_CATALOG[domain_id]
    return {
        "domain": domain_id,
        "Domain": _pascal_case(domain_id),
        "name": meta["name"],
        "description": meta["description"],
        "status": status,
        "tags_json": json.dumps(meta["tags"], indent=2),
    }


def _manifest_template(context: dict[str, Any]) -> dict[str, Any]:
    raw = _render(_load_template("manifest.json"), context)
    return json.loads(raw)


def _write_file(path: Path, content: str, *, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _merge_skeleton_manifest(existing: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
    """Add skeleton fields to legacy placeholder manifests without clobbering content."""
    merged = dict(existing)
    for key in (
        "container",
        "prompts",
        "data",
        "core_modules",
        "skeleton_artifacts",
        "install_requires",
        "source",
    ):
        if key not in merged or not merged[key]:
            merged[key] = generated[key]
    if merged.get("version") in (None, "", "0.0.0-placeholder"):
        merged["version"] = generated["version"]
    merged.setdefault("artifacts", [])
    merged.setdefault("blocks", existing.get("blocks") or [])
    merged.setdefault("id", generated["id"])
    merged.setdefault("author", generated.get("author", "bopoadz-del"))
    merged.setdefault("price_cents", generated.get("price_cents", 0))
    return merged


def _connector_stub_content(domain_id: str, rel_path: str, context: dict[str, Any]) -> str | None:
    """Return stub source for known connector files, or None to skip."""
    name = Path(rel_path).stem
    domain = context["Domain"]
    if name.endswith("_connector"):
        return (
            f'"""Kit stub — {name} for {domain} domain."""\n\n'
            f"from app.blocks.core.base_connector import BaseConnector\n\n\n"
            f"class {domain}{''.join(p.capitalize() for p in name.split('_'))}Block(BaseConnector):\n"
            f'    name = "{name}"\n'
            f'    version = "0.1.0-skeleton"\n'
            f'    description = "{name.replace("_", " ").title()} (generated stub)"\n'
            f"    connector_source = \"{domain_id}_{name}\"\n\n"
            f"    async def fetch_raw(self, input_data, params):\n"
            f'        return {{"stub": True, "connector": self.name}}\n'
        )
    if name.endswith("_trigger"):
        return (
            f'"""Kit stub — {name} for {domain} domain."""\n\n'
            f"from typing import Any, Dict\n"
            f"from app.core.universal_base import UniversalBlock\n\n\n"
            f"class {domain}{''.join(p.capitalize() for p in name.split('_'))}Block(UniversalBlock):\n"
            f'    name = "{name}"\n'
            f'    version = "0.1.0-skeleton"\n'
            f"    tags = [\"{domain_id}\", \"trigger\", \"stub\"]\n\n"
            f"    async def process(self, input_data: Any, params: Dict = None) -> Dict:\n"
            f'        return {{"status": "success", "triggered": False, "stub": True}}\n'
        )
    if name == "video_metadata_ingest":
        return (
            '"""Uses platform video_metadata_ingest block."""\n\n'
            "from app.blocks.video_metadata_ingest import VideoMetadataIngestBlock\n\n"
            "__all__ = [\"VideoMetadataIngestBlock\"]\n"
        )
    return None


def generate_domain_kit(
    domain_id: str,
    *,
    force: bool = False,
    coming_soon: bool = False,
    with_connectors: bool = False,
    quiet: bool = False,
) -> list[str]:
    if domain_id in SKIP_KITS:
        raise ValueError(f"Refusing to generate skeleton for protected kit '{domain_id}'")
    if domain_id not in DOMAIN_CATALOG:
        raise ValueError(f"Unknown domain '{domain_id}'. Use --list for catalog domains.")

    status = "coming_soon" if coming_soon else "draft"
    context = _build_context(domain_id, status=status)
    kit_dir = KITS_DIR / domain_id
    created: list[str] = []

    manifest_path = kit_dir / "manifest.json"
    generated_manifest = _manifest_template(context)

    if not manifest_path.exists():
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(generated_manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        created.append("manifest.json")
    elif force:
        manifest_path.write_text(
            json.dumps(generated_manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        created.append("manifest.json")
    else:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not existing.get("skeleton_artifacts"):
            merged = _merge_skeleton_manifest(existing, generated_manifest)
            manifest_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
            created.append("manifest.json (upgraded skeleton fields)")

    for rel in SKELETON_FILES:
        rel_rendered = rel.format(domain=domain_id)
        template_rel = rel_rendered
        if rel.startswith(_DOMAIN_NAMED_DIRS):
            template_rel = rel.replace("{domain}", "{{domain}}")
        content = _render(_load_template(template_rel), context)
        dest = kit_dir / rel_rendered
        if _write_file(dest, content, force=force):
            created.append(rel_rendered)

    if with_connectors:
        for rel in CONNECTOR_STUBS.get(domain_id, []):
            dest = kit_dir / rel
            stub = _connector_stub_content(domain_id, rel, context)
            if stub and _write_file(dest, stub, force=force):
                created.append(rel)

    if not quiet:
        if created:
            print(f"[{domain_id}] created/updated: {', '.join(created)}")
        else:
            print(f"[{domain_id}] nothing to do (use --force to overwrite)")
    return created


def list_domains() -> None:
    print("Catalog domains (skeleton generator):")
    for domain_id, meta in sorted(DOMAIN_CATALOG.items()):
        print(f"  {domain_id:20}  {meta['name']}")
    print("\nProtected (skipped):", ", ".join(sorted(SKIP_KITS)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate domain kit skeletons")
    parser.add_argument("domain", nargs="?", help="Domain kit id (e.g. medical)")
    parser.add_argument("--all", action="store_true", help="Generate all catalog domains")
    parser.add_argument("--list", action="store_true", help="List catalog domains")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    parser.add_argument(
        "--coming-soon",
        action="store_true",
        help='Set manifest status to "coming_soon" (default: draft)',
    )
    parser.add_argument(
        "--with-connectors",
        action="store_true",
        help="Generate connector/trigger block stubs for supported domains",
    )
    args = parser.parse_args()

    if args.list:
        list_domains()
        return 0

    if args.all:
        errors = 0
        for domain_id in sorted(DOMAIN_CATALOG):
            try:
                generate_domain_kit(
                    domain_id,
                    force=args.force,
                    coming_soon=args.coming_soon,
                    with_connectors=args.with_connectors,
                )
            except (ValueError, FileNotFoundError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                errors += 1
        return 1 if errors else 0

    if not args.domain:
        parser.print_help()
        return 1

    try:
        generate_domain_kit(
            args.domain,
            force=args.force,
            coming_soon=args.coming_soon,
            with_connectors=args.with_connectors,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
