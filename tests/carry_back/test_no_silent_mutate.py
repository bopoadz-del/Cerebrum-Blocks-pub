"""Proposal-only / no silent mutate on main."""

from __future__ import annotations

from pathlib import Path

import pytest

from carry_back.seeds import seed_dir
from carry_back import LIVE_ENABLED
from carry_back.guardrails import (
    GuardrailViolation,
    assert_mode_allowed,
    assert_not_pushing_main,
    assert_proposal_branch,
    assert_writes_scoped,
)
from carry_back.modes import Mode
from carry_back.propose import propose_from_fixture

STORE_ROOT = Path(__file__).resolve().parents[2]


def test_live_gated():
    assert LIVE_ENABLED is False
    with pytest.raises(GuardrailViolation, match="NOT LIVE|gated"):
        assert_mode_allowed(Mode.LIVE)


def test_refuse_push_main():
    with pytest.raises(GuardrailViolation):
        assert_not_pushing_main("main")
    with pytest.raises(GuardrailViolation):
        assert_not_pushing_main("origin/main")
    assert_not_pushing_main("carry-back/cb-test")  # ok


def test_proposal_branch_prefix():
    with pytest.raises(GuardrailViolation):
        assert_proposal_branch("feat/oops")
    assert_proposal_branch("carry-back/cb-123")


def test_writes_on_main_cannot_touch_blocks(tmp_path):
    store = tmp_path
    (store / "app" / "blocks").mkdir(parents=True)
    bad = store / "app" / "blocks" / "pdf.py"
    bad.write_text("# no\n", encoding="utf-8")
    with pytest.raises(GuardrailViolation, match="Refusing to mutate"):
        assert_writes_scoped(store, [bad], on_main_worktree=True)

    ok = store / ".carry_back" / "proposals" / "cb-1" / "x.diff"
    ok.parent.mkdir(parents=True)
    ok.write_text("diff\n", encoding="utf-8")
    assert_writes_scoped(store, [ok], on_main_worktree=True)


def test_propose_does_not_modify_store_block_file():
    pdf = STORE_ROOT / "app" / "blocks" / "pdf.py"
    before = pdf.read_bytes()
    propose_from_fixture(
        STORE_ROOT,
        seed_dir() / "block_level_fix",
        mode=Mode.PROPOSE,
    )
    after = pdf.read_bytes()
    assert before == after
