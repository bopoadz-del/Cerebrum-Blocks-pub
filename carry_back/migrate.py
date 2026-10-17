"""Propose a store-block migration patch (never applied to main silently)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from carry_back.classify import ClassifyResult


@dataclass(frozen=True)
class MigrationProposal:
    block_name: str
    store_target: str  # e.g. app/blocks/pdf.py
    unified_diff: str
    source_excerpt: str
    notes: str


def _preferred_store_target(store_root: Path, block_name: str) -> Path | None:
    app_block = store_root / "app" / "blocks" / f"{block_name}.py"
    if app_block.is_file():
        return app_block
    registry = store_root / "block_registry" / block_name / "block.py"
    if registry.is_file():
        return registry
    return None


def _extract_file_diff(diff_text: str, path_suffix: str) -> str | None:
    """Return the unified diff hunk for a file whose path ends with path_suffix."""
    lines = diff_text.splitlines(keepends=True)
    chunks: list[str] = []
    capturing = False
    current: list[str] = []
    for line in lines:
        if line.startswith("diff --git "):
            if capturing and current:
                chunks.append("".join(current))
            current = [line]
            capturing = path_suffix.replace("\\", "/") in line.replace("\\", "/")
            continue
        if capturing:
            current.append(line)
    if capturing and current:
        chunks.append("".join(current))
    if not chunks:
        return None
    return "".join(chunks)


def propose_migration(
    *,
    store_root: Path,
    classify: ClassifyResult,
    product_diff: str,
    bug_class: str,
    source_product: str,
) -> list[MigrationProposal]:
    """Build migration proposal artifacts from a product diff (no apply)."""
    if not classify.should_propose:
        return []

    proposals: list[MigrationProposal] = []
    for block_name in classify.block_names:
        target = _preferred_store_target(store_root, block_name)
        if target is None:
            continue
        rel = str(target.relative_to(store_root)).replace("\\", "/")
        file_diff = _extract_file_diff(product_diff, f"app/blocks/{block_name}.py")
        if not file_diff:
            file_diff = _extract_file_diff(product_diff, f"block_registry/{block_name}/")
        if not file_diff:
            # Synthesize a proposal note when only paths.txt was provided.
            file_diff = (
                f"diff --git a/{rel} b/{rel}\n"
                f"--- a/{rel}\n"
                f"+++ b/{rel}\n"
                f"@@\n"
                f"+# carry-back proposed migration for bug class: {bug_class}\n"
                f"+# source product: {source_product}\n"
                f"+# TODO: apply product hunk to this store block (librarian review)\n"
            )
        # Remap product paths to store target in the proposal diff header.
        remapped = re.sub(
            rf"(a|b)/[^\s]*app/blocks/{re.escape(block_name)}\.py",
            rf"\1/{rel}",
            file_diff,
        )
        proposals.append(
            MigrationProposal(
                block_name=block_name,
                store_target=rel,
                unified_diff=remapped,
                source_excerpt=product_diff[:4000],
                notes=(
                    f"Proposed carry-back of {bug_class!r} from {source_product} "
                    f"into store block {block_name} ({rel}). Proposal-only — not applied."
                ),
            )
        )
    return proposals


def write_migration_artifacts(
    proposal_dir: Path, migrations: list[MigrationProposal]
) -> list[Path]:
    proposal_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    index_lines = ["# Migration proposals (not applied to main)", ""]
    for mig in migrations:
        out = proposal_dir / f"migrate_{mig.block_name}.diff"
        out.write_text(mig.unified_diff, encoding="utf-8")
        written.append(out)
        notes = proposal_dir / f"migrate_{mig.block_name}.notes.md"
        notes.write_text(
            f"# Migration: `{mig.block_name}`\n\n"
            f"- Store target: `{mig.store_target}`\n"
            f"- {mig.notes}\n",
            encoding="utf-8",
        )
        written.append(notes)
        index_lines.append(f"- `{mig.block_name}` → `{mig.store_target}` ({out.name})")
    index = proposal_dir / "migrations.md"
    index.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    written.append(index)
    return written
