"""Block-level propose acceptance."""

from __future__ import annotations

from pathlib import Path

from carry_back.seeds import seed_dir
from carry_back.modes import Mode
from carry_back.propose import propose_from_fixture

STORE_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = seed_dir() / "block_level_fix"


def test_propose_block_level_package(tmp_path, monkeypatch):
    # Isolate proposal writes under a temp store root that mirrors needed files.
    # Use real store root so pdf block + consumers.yaml resolve; proposals go to .carry_back.
    result = propose_from_fixture(
        STORE_ROOT,
        FIXTURE,
        mode=Mode.PROPOSE,
        open_pr=True,
        on_main_worktree=True,
    )
    assert not result.declined
    assert result.classification == "block_level"
    assert "pdf" in result.block_names
    assert result.proposal_path
    assert result.pr_payload is not None
    assert result.pr_payload["head_branch"].startswith("carry-back/")
    assert result.pr_create_result and result.pr_create_result.get("dry_run") is True

    arts = result.artifacts
    assert any("migrate_pdf.diff" in a for a in arts)
    assert any("test_pin_pdf" in a for a in arts)
    assert any("test_seam_stub_pdf" in a for a in arts)
    assert any(a.endswith("ledger_entry.md") for a in arts)
    assert any(a.endswith("fanout.md") for a in arts)
    assert any(a.endswith("pr_payload.json") for a in arts)

    # Fan-out should flag known consumers that list pdf / shared_generics
    assert result.fanout_products
    assert "The_Fork" in result.fanout_products

    prop = Path(result.proposal_path)
    assert (prop / "migrate_pdf.diff").is_file()
    assert (prop / "tests" / "MANIFEST.md").is_file()
    body = (prop / "pr_body.md").read_text(encoding="utf-8")
    assert "Classification" in body
    assert "pdf" in body.lower()
