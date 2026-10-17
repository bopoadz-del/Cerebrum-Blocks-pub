"""Extinction Ledger — append-only proposal entries (store crown jewels audit trail)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


LEDGER_FILENAME = "EXTINCTION_LEDGER.md"


@dataclass(frozen=True)
class LedgerEntry:
    bug_class: str
    found_on_product: str
    extinct_across_products: tuple[str, ...]
    pinned_by_tests: tuple[str, ...]
    block_name: str
    proposal_id: str
    source_ref: str
    status: str = "proposed"  # proposed | merged | declined
    recorded_at: str = ""

    def with_timestamp(self) -> "LedgerEntry":
        if self.recorded_at:
            return self
        return LedgerEntry(
            **{
                **asdict(self),
                "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )


def default_ledger_path(store_root: Path) -> Path:
    return store_root / LEDGER_FILENAME


def format_entry_markdown(entry: LedgerEntry) -> str:
    e = entry.with_timestamp()
    products = ", ".join(e.extinct_across_products) or "_(pending fan-out)_"
    tests = ", ".join(f"`{t}`" for t in e.pinned_by_tests) or "_(none)_"
    return "\n".join(
        [
            f"## {e.bug_class}",
            "",
            f"- **Status:** {e.status}",
            f"- **Proposal ID:** `{e.proposal_id}`",
            f"- **Block:** `{e.block_name}`",
            f"- **Found on:** {e.found_on_product}",
            f"- **Source:** {e.source_ref}",
            f"- **Now extinct across:** {products}",
            f"- **Pinned by tests:** {tests}",
            f"- **Recorded at:** {e.recorded_at}",
            "",
        ]
    )


def ensure_ledger_skeleton(store_root: Path) -> Path:
    path = default_ledger_path(store_root)
    if path.is_file():
        return path
    path.write_text(
        "\n".join(
            [
                "# Extinction Ledger",
                "",
                "Audit trail for Carry-Back (Pillar C): bug classes carried into the store,",
                "pinned by tests, and extinct across consuming products.",
                "",
                "> Format: *bug class X, found on product Y, now extinct across N consuming",
                "> products, pinned by tests T.*",
                "",
                "Entries below are **proposed** until a store PR merges.",
                "",
                "---",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def draft_ledger_entry_file(proposal_dir: Path, entry: LedgerEntry) -> Path:
    """Write a ledger *draft* into the proposal package (does not mutate main ledger)."""
    proposal_dir.mkdir(parents=True, exist_ok=True)
    out = proposal_dir / "ledger_entry.md"
    out.write_text(
        "# Ledger draft (append on merge)\n\n" + format_entry_markdown(entry),
        encoding="utf-8",
    )
    return out


def append_ledger_proposal(
    store_root: Path,
    entry: LedgerEntry,
    *,
    apply_to_main_ledger: bool = False,
) -> Path:
    """Optionally append to EXTINCTION_LEDGER.md — only when explicitly requested.

    Default False: proposals keep the draft under .carry_back/proposals/<id>/.
    Applying to the main ledger file is for proposal-branch commits, never silent main.
    """
    if not apply_to_main_ledger:
        raise ValueError(
            "Refusing silent ledger mutate; pass apply_to_main_ledger=True only on "
            "a carry-back/* proposal branch commit."
        )
    path = ensure_ledger_skeleton(store_root)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(format_entry_markdown(entry))
    return path


def parse_ledger_bug_classes(store_root: Path) -> Sequence[str]:
    path = default_ledger_path(store_root)
    if not path.is_file():
        return []
    classes: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## ") and not line.startswith("## "):
            continue
        if line.startswith("## "):
            classes.append(line[3:].strip())
    return classes
