"""Least-privilege / proposal-only guardrails for Carry-Back."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from carry_back import LIVE_ENABLED
from carry_back.modes import Mode

# Paths that may never be written by Carry-Back on the default branch tip.
FORBIDDEN_MAIN_TOUCHES = (
    "app/blocks/",
    "block_registry/",
    "block_store/",
)

PROPOSAL_ROOT_NAME = ".carry_back"
PROPOSAL_BRANCH_PREFIX = "carry-back/"


class GuardrailViolation(Exception):
    """Raised when an operation would breach proposal-only rules."""


def assert_mode_allowed(mode: Mode) -> None:
    if mode is Mode.LIVE and not LIVE_ENABLED:
        raise GuardrailViolation(
            "LIVE mode is gated: Carry-Back is NOT LIVE until one real "
            "block-level migration and one correct platform-specific decline "
            "are recorded. Use --mode propose or --mode dry-run."
        )


def assert_not_pushing_main(remote_ref: str | None) -> None:
    """Refuse using main/master as a *push target* (head), not as a PR base."""
    if not remote_ref:
        return
    ref = remote_ref.strip().lower()
    if ref in {"main", "master", "refs/heads/main", "refs/heads/master", "origin/main", "origin/master"}:
        raise GuardrailViolation(
            f"Refusing to push or update protected branch {remote_ref!r}. "
            "Carry-Back opens PRs from carry-back/<id> only."
        )


def assert_pr_base_is_main(base_branch: str) -> None:
    """PRs must target the store main for <owner>'s approval."""
    if base_branch.strip().lower() not in {"main", "master"}:
        raise GuardrailViolation(
            f"Carry-Back PRs must target main/master, got {base_branch!r}"
        )


def assert_proposal_branch(branch: str) -> None:
    if not branch.startswith(PROPOSAL_BRANCH_PREFIX):
        raise GuardrailViolation(
            f"Proposal branch must start with {PROPOSAL_BRANCH_PREFIX!r}, got {branch!r}"
        )


def assert_writes_scoped(
    store_root: Path,
    written_paths: Iterable[Path],
    *,
    on_main_worktree: bool,
) -> None:
    """On main worktree tip, only proposal artifact dirs may be written."""
    if not on_main_worktree:
        return
    root = store_root.resolve()
    proposal_root = (root / PROPOSAL_ROOT_NAME).resolve()
    for raw in written_paths:
        path = Path(raw)
        if not path.is_absolute():
            path = (root / path).resolve()
        else:
            path = path.resolve()
        try:
            path.relative_to(proposal_root)
            continue
        except ValueError:
            pass
        rel = str(path.relative_to(root)).replace("\\", "/")
        for prefix in FORBIDDEN_MAIN_TOUCHES:
            if rel.startswith(prefix) or rel == prefix.rstrip("/"):
                raise GuardrailViolation(
                    f"Refusing to mutate store path {rel!r} on main worktree. "
                    "Write under .carry_back/proposals/<id>/ or a carry-back/* branch."
                )


def proposal_dir(store_root: Path, proposal_id: str) -> Path:
    return store_root / PROPOSAL_ROOT_NAME / "proposals" / proposal_id
