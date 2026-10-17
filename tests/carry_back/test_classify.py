"""Classification heuristics for Carry-Back."""

from __future__ import annotations

from pathlib import Path

from carry_back.seeds import seed_dir
from carry_back.classify import (
    Classification,
    classify_diff,
    classify_fixture_dir,
    classify_paths,
    filter_known_blocks,
)

STORE_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = seed_dir()


def test_block_level_paths():
    result = classify_paths(["app/blocks/pdf.py"])
    assert result.classification is Classification.BLOCK_LEVEL
    assert result.block_names == ("pdf",)
    assert result.should_propose


def test_platform_specific_paths():
    result = classify_paths(
        ["render.yaml", "frontend/src/App.tsx", "app/routers/health.py"]
    )
    assert result.classification is Classification.PLATFORM_SPECIFIC
    assert not result.should_propose


def test_mixed_needs_human():
    result = classify_paths(["app/blocks/pdf.py", "render.yaml"])
    assert result.classification is Classification.NEEDS_HUMAN
    assert not result.should_propose


def test_ambiguous_declines():
    result = classify_paths(["docs/README.md", "scripts/foo.sh"])
    assert result.classification is Classification.DECLINED_AMBIGUOUS
    assert not result.should_propose


def test_fixture_block_level():
    result = filter_known_blocks(
        classify_fixture_dir(FIXTURES / "block_level_fix"), STORE_ROOT
    )
    assert result.classification is Classification.BLOCK_LEVEL
    assert "pdf" in result.block_names


def test_fixture_platform_specific():
    result = classify_fixture_dir(FIXTURES / "platform_specific_fix")
    assert result.classification is Classification.PLATFORM_SPECIFIC


def test_classify_diff_extracts_paths():
    diff = (FIXTURES / "block_level_fix" / "diff.patch").read_text(encoding="utf-8")
    result = classify_diff(diff)
    assert result.classification is Classification.BLOCK_LEVEL
