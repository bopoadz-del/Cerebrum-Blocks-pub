"""Extinction Ledger draft behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from carry_back.ledger import (
    LedgerEntry,
    append_ledger_proposal,
    draft_ledger_entry_file,
    ensure_ledger_skeleton,
    format_entry_markdown,
)

STORE_ROOT = Path(__file__).resolve().parents[2]


def test_format_and_draft(tmp_path):
    entry = LedgerEntry(
        bug_class="pdf-empty-path-npe",
        found_on_product="The_Fork",
        extinct_across_products=("The_Fork", "FinanceOps"),
        pinned_by_tests=("test_pin_pdf_pdf_empty_path_npe.py",),
        block_name="pdf",
        proposal_id="cb-test-001",
        source_ref="fixture",
    )
    md = format_entry_markdown(entry)
    assert "pdf-empty-path-npe" in md
    assert "The_Fork" in md
    out = draft_ledger_entry_file(tmp_path, entry)
    assert out.is_file()
    assert "Ledger draft" in out.read_text(encoding="utf-8")


def test_refuse_silent_ledger_append():
    entry = LedgerEntry(
        bug_class="x",
        found_on_product="y",
        extinct_across_products=(),
        pinned_by_tests=(),
        block_name="pdf",
        proposal_id="cb-x",
        source_ref="t",
    )
    with pytest.raises(ValueError, match="Refusing silent ledger mutate"):
        append_ledger_proposal(STORE_ROOT, entry, apply_to_main_ledger=False)


def test_skeleton_exists_or_creatable():
    path = ensure_ledger_skeleton(STORE_ROOT)
    assert path.name == "EXTINCTION_LEDGER.md"
    assert path.is_file()
