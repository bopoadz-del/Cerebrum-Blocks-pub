"""Classify a product fix as block-level vs platform-specific (v0 heuristics)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Sequence

# Block identity paths present in the store.
BLOCK_PATH_PATTERNS = (
    re.compile(r"(?:^|/)app/blocks/([^/]+)\.py$"),
    re.compile(r"(?:^|/)block_registry/([^/]+)/"),
    re.compile(r"(?:^|/)block_store/kits/[^/]+/bundle/app/blocks/([^/]+)\.py$"),
)

# Explicitly platform-local — never migrate.
PLATFORM_PATH_PATTERNS = (
    re.compile(r"(?:^|/)frontend/"),
    re.compile(r"(?:^|/)app/static/"),
    re.compile(r"(?:^|/)render\.ya?ml$"),
    re.compile(r"(?:^|/)Dockerfile$"),
    re.compile(r"(?:^|/)docker-compose\.ya?ml$"),
    re.compile(r"(?:^|/)\.env"),
    re.compile(r"(?:^|/)app/routers/"),
    re.compile(r"(?:^|/)deploy/"),
    re.compile(r"oauth|drive_auth|credentials", re.I),
)


class Classification(str, Enum):
    BLOCK_LEVEL = "block_level"
    PLATFORM_SPECIFIC = "platform_specific"
    NEEDS_HUMAN = "needs_human_classification"
    DECLINED_AMBIGUOUS = "declined_ambiguous"


@dataclass(frozen=True)
class ClassifyResult:
    classification: Classification
    block_names: tuple[str, ...] = ()
    block_paths: tuple[str, ...] = ()
    platform_paths: tuple[str, ...] = ()
    touched_paths: tuple[str, ...] = ()
    rationale: str = ""
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def should_propose(self) -> bool:
        return self.classification is Classification.BLOCK_LEVEL and bool(self.block_names)


def _normalize_path(path: str) -> str:
    return str(PurePosixPath(path.replace("\\", "/").lstrip("./")))


def _extract_changed_paths(diff_text: str) -> list[str]:
    paths: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            raw = line[6:].strip()
            if raw and raw != "/dev/null":
                paths.append(_normalize_path(raw))
        elif line.startswith("diff --git "):
            # diff --git a/foo b/foo
            parts = line.split()
            if len(parts) >= 4:
                paths.append(_normalize_path(parts[3].removeprefix("b/")))
    # preserve order, unique
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _match_block(path: str) -> str | None:
    for pat in BLOCK_PATH_PATTERNS:
        m = pat.search(path)
        if m:
            return m.group(1)
    return None


def _is_platform(path: str) -> bool:
    return any(pat.search(path) for pat in PLATFORM_PATH_PATTERNS)


def classify_paths(paths: Sequence[str]) -> ClassifyResult:
    normalized = [_normalize_path(p) for p in paths]
    block_names: list[str] = []
    block_paths: list[str] = []
    platform_paths: list[str] = []
    other: list[str] = []
    reasons: list[str] = []

    for path in normalized:
        block = _match_block(path)
        if block:
            block_names.append(block)
            block_paths.append(path)
            reasons.append(f"block identity path: {path} → {block}")
            continue
        if _is_platform(path):
            platform_paths.append(path)
            reasons.append(f"platform-specific path: {path}")
            continue
        other.append(path)
        reasons.append(f"unclassified path: {path}")

    uniq_blocks = tuple(dict.fromkeys(block_names))

    if uniq_blocks and not platform_paths and not other:
        return ClassifyResult(
            classification=Classification.BLOCK_LEVEL,
            block_names=uniq_blocks,
            block_paths=tuple(block_paths),
            platform_paths=(),
            touched_paths=tuple(normalized),
            rationale=(
                f"Fix touches store block identity path(s) only: {', '.join(uniq_blocks)}"
            ),
            reasons=tuple(reasons),
        )

    if platform_paths and not uniq_blocks:
        return ClassifyResult(
            classification=Classification.PLATFORM_SPECIFIC,
            block_names=(),
            block_paths=(),
            platform_paths=tuple(platform_paths),
            touched_paths=tuple(normalized),
            rationale="Fix is product/platform-local (UI, deploy, routers, OAuth, env, etc.).",
            reasons=tuple(reasons),
        )

    if uniq_blocks and platform_paths:
        return ClassifyResult(
            classification=Classification.NEEDS_HUMAN,
            block_names=uniq_blocks,
            block_paths=tuple(block_paths),
            platform_paths=tuple(platform_paths),
            touched_paths=tuple(normalized),
            rationale=(
                "Mixed block + platform paths — declining forced migrate; "
                "needs_human_classification."
            ),
            reasons=tuple(reasons),
        )

    # Only unclassified / ambiguous → decline, never force migrate.
    return ClassifyResult(
        classification=Classification.DECLINED_AMBIGUOUS,
        block_names=(),
        block_paths=(),
        platform_paths=tuple(platform_paths),
        touched_paths=tuple(normalized),
        rationale=(
            "No clear store block identity path; declining migration "
            "(ambiguous / needs_human_classification)."
        ),
        reasons=tuple(reasons),
    )


def classify_diff(diff_text: str) -> ClassifyResult:
    return classify_paths(_extract_changed_paths(diff_text))


def classify_fixture_dir(fixture_dir: Path) -> ClassifyResult:
    """Classify from a fixture directory containing `diff.patch` and/or `paths.txt`."""
    paths_file = fixture_dir / "paths.txt"
    diff_file = fixture_dir / "diff.patch"
    meta_file = fixture_dir / "meta.yaml"

    paths: list[str] = []
    if paths_file.is_file():
        paths.extend(
            line.strip()
            for line in paths_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    if diff_file.is_file():
        result_from_diff = classify_diff(diff_file.read_text(encoding="utf-8"))
        if not paths:
            return result_from_diff
        # Prefer explicit paths.txt when both present; still merge for touched.
        path_result = classify_paths(paths)
        return path_result

    if paths:
        return classify_paths(paths)

    if meta_file.is_file():
        # Minimal YAML-free parse for expected_classification / paths list
        text = meta_file.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.strip().startswith("- "):
                paths.append(line.strip()[2:].strip().strip("\"'"))
        if paths:
            return classify_paths(paths)

    raise FileNotFoundError(
        f"Fixture {fixture_dir} needs paths.txt, diff.patch, or meta.yaml with paths"
    )


def list_store_block_names(store_root: Path) -> set[str]:
    names: set[str] = set()
    blocks_dir = store_root / "app" / "blocks"
    if blocks_dir.is_dir():
        for p in blocks_dir.glob("*.py"):
            if p.name != "__init__.py":
                names.add(p.stem)
    registry = store_root / "block_registry"
    if registry.is_dir():
        for p in registry.iterdir():
            if p.is_dir() and not p.name.startswith("_"):
                names.add(p.name)
    return names


def filter_known_blocks(
    result: ClassifyResult, store_root: Path
) -> ClassifyResult:
    """If block names are not in the store, downgrade to needs_human."""
    known = list_store_block_names(store_root)
    if not result.block_names:
        return result
    unknown = [b for b in result.block_names if b not in known]
    if not unknown:
        return result
    return ClassifyResult(
        classification=Classification.NEEDS_HUMAN,
        block_names=result.block_names,
        block_paths=result.block_paths,
        platform_paths=result.platform_paths,
        touched_paths=result.touched_paths,
        rationale=(
            f"Block name(s) not found in store: {', '.join(unknown)}. "
            "needs_human_classification — never force migrate."
        ),
        reasons=result.reasons + (f"unknown blocks: {unknown}",),
    )
