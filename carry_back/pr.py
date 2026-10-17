"""PR payload builder for store Carry-Back proposals (gh pr create)."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from carry_back.guardrails import (
    GuardrailViolation,
    assert_not_pushing_main,
    assert_pr_base_is_main,
    assert_proposal_branch,
)


@dataclass
class PrPayload:
    title: str
    body: str
    head_branch: str
    base_branch: str = "main"
    draft: bool = True
    labels: list[str] = field(default_factory=lambda: ["carry-back", "proposal-only"])

    def to_dict(self) -> dict:
        return asdict(self)


def build_pr_body(
    *,
    classification: str,
    source_product: str,
    source_ref: str,
    block_names: list[str],
    tests_added: list[str],
    fanout_products: list[str],
    ledger_draft_summary: str,
    proposal_id: str,
    mode: str,
) -> str:
    blocks = ", ".join(f"`{b}`" for b in block_names) or "_(none)_"
    tests = "\n".join(f"- `{t}`" for t in tests_added) or "- _(none)_"
    fanout = "\n".join(f"- {p}" for p in fanout_products) or "- _(none matched)_"
    return f"""## Carry-Back proposal `{proposal_id}`

**Librarian, not author.** Proposal-only — does not silently mutate the store.

### Classification
`{classification}`

### Source
- Product: **{source_product}**
- Ref: {source_ref}
- Mode: `{mode}`

### Block(s)
{blocks}

### Tests added
{tests}

### Fan-out (needs fix on next build)
{fanout}

### Ledger draft
{ledger_draft_summary}

### Guardrails
- Never push to `main`
- Every migration carries its pinning test or it does not merge
- Seam stubs are Pillar A hooks (not full auto seam generation yet)
"""


def build_pr_payload(
    *,
    proposal_id: str,
    block_names: list[str],
    classification: str,
    source_product: str,
    source_ref: str,
    tests_added: list[str],
    fanout_products: list[str],
    ledger_draft_summary: str,
    mode: str,
) -> PrPayload:
    blocks = ", ".join(block_names) if block_names else "decline"
    title = f"carry-back({proposal_id}): {blocks} from {source_product}"
    head = f"carry-back/{proposal_id}"
    assert_proposal_branch(head)
    body = build_pr_body(
        classification=classification,
        source_product=source_product,
        source_ref=source_ref,
        block_names=block_names,
        tests_added=tests_added,
        fanout_products=fanout_products,
        ledger_draft_summary=ledger_draft_summary,
        proposal_id=proposal_id,
        mode=mode,
    )
    return PrPayload(title=title, body=body, head_branch=head)


def write_pr_payload(proposal_dir: Path, payload: PrPayload) -> Path:
    proposal_dir.mkdir(parents=True, exist_ok=True)
    out = proposal_dir / "pr_payload.json"
    out.write_text(json.dumps(payload.to_dict(), indent=2) + "\n", encoding="utf-8")
    body = proposal_dir / "pr_body.md"
    body.write_text(payload.body, encoding="utf-8")
    return out


GhRunner = Callable[[list[str]], subprocess.CompletedProcess]


def default_gh_runner(args: list[str]) -> subprocess.CompletedProcess:
    gh = shutil.which("gh")
    if not gh:
        raise FileNotFoundError("gh CLI not found on PATH")
    return subprocess.run([gh, *args], capture_output=True, text=True, check=False)


def create_pr(
    payload: PrPayload,
    *,
    runner: GhRunner | None = None,
    push_first: bool = False,
    dry_run: bool = True,
) -> dict:
    """Create a PR against the store. Default dry_run=True (no network)."""
    assert_proposal_branch(payload.head_branch)
    assert_pr_base_is_main(payload.base_branch)
    # Never push the head if it resolves to main (defense in depth).
    assert_not_pushing_main(
        None if payload.head_branch.startswith("carry-back/") else payload.head_branch
    )

    cmd = [
        "pr",
        "create",
        "--title",
        payload.title,
        "--body",
        payload.body,
        "--base",
        payload.base_branch,
        "--head",
        payload.head_branch,
    ]
    if payload.draft:
        cmd.append("--draft")

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "command": ["gh", *cmd],
            "payload": payload.to_dict(),
        }

    run = runner or default_gh_runner
    if push_first:
        # Still never push main — only the proposal head.
        assert_not_pushing_main(payload.head_branch)
        push = subprocess.run(
            ["git", "push", "-u", "origin", payload.head_branch],
            capture_output=True,
            text=True,
            check=False,
        )
        if push.returncode != 0:
            raise GuardrailViolation(f"git push failed: {push.stderr}")

    result = run(cmd)
    return {
        "ok": result.returncode == 0,
        "dry_run": False,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "payload": payload.to_dict(),
    }
