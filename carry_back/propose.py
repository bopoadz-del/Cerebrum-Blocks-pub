"""Orchestrate classify → propose (or decline) for Carry-Back."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from carry_back.classify import (
    Classification,
    ClassifyResult,
    classify_diff,
    classify_fixture_dir,
    filter_known_blocks,
)
from carry_back.fanout import fanout_for_block, write_fanout_report
from carry_back.guardrails import (
    GuardrailViolation,
    assert_mode_allowed,
    assert_writes_scoped,
    proposal_dir as proposal_dir_for,
)
from carry_back.ledger import LedgerEntry, draft_ledger_entry_file
from carry_back.migrate import propose_migration, write_migration_artifacts
from carry_back.modes import Mode, parse_mode
from carry_back.pr import build_pr_payload, create_pr, write_pr_payload
from carry_back.tests_writer import write_test_artifacts


@dataclass
class ProposeResult:
    proposal_id: str
    mode: str
    classification: str
    declined: bool
    rationale: str
    proposal_path: str | None
    block_names: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    pr_payload: dict[str, Any] | None = None
    pr_create_result: dict[str, Any] | None = None
    fanout_products: list[str] = field(default_factory=list)
    live_status: str = "NOT LIVE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return (s[:40] or "fix")


def make_proposal_id(
    *,
    source_product: str,
    bug_class: str,
    seed: str | None = None,
) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    base = f"{_slug(source_product)}-{_slug(bug_class)}-{stamp}"
    if seed:
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
        return f"cb-{_slug(source_product)}-{digest}"
    return f"cb-{base}"


def _load_product_diff(fixture_or_diff: Path) -> str:
    if fixture_or_diff.is_dir():
        patch = fixture_or_diff / "diff.patch"
        if patch.is_file():
            return patch.read_text(encoding="utf-8")
        return ""
    return fixture_or_diff.read_text(encoding="utf-8")


def _load_meta(fixture_dir: Path | None) -> dict[str, str]:
    meta: dict[str, str] = {}
    if fixture_dir is None or not fixture_dir.is_dir():
        return meta
    meta_path = fixture_dir / "meta.yaml"
    if not meta_path.is_file():
        return meta
    for line in meta_path.read_text(encoding="utf-8").splitlines():
        if ":" in line and not line.strip().startswith("-") and not line.strip().startswith("#"):
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip("\"'")
    return meta


def propose_from_fixture(
    store_root: Path,
    fixture_dir: Path,
    *,
    mode: Mode | str = Mode.PROPOSE,
    open_pr: bool = False,
    on_main_worktree: bool = True,
) -> ProposeResult:
    fixture_dir = fixture_dir.resolve()
    meta = _load_meta(fixture_dir)
    source_product = meta.get("source_product", "fixture-product")
    bug_class = meta.get("bug_class", "unspecified-bug-class")
    source_ref = meta.get("source_ref", str(fixture_dir))
    classify = filter_known_blocks(classify_fixture_dir(fixture_dir), store_root)
    product_diff = _load_product_diff(fixture_dir)
    seed = product_diff or "\n".join(classify.touched_paths)
    return run_propose(
        store_root=store_root,
        classify=classify,
        product_diff=product_diff,
        source_product=source_product,
        bug_class=bug_class,
        source_ref=source_ref,
        mode=mode,
        open_pr=open_pr,
        on_main_worktree=on_main_worktree,
        proposal_id_seed=seed,
    )


def run_propose(
    *,
    store_root: Path,
    classify: ClassifyResult,
    product_diff: str,
    source_product: str,
    bug_class: str,
    source_ref: str,
    mode: Mode | str = Mode.PROPOSE,
    open_pr: bool = False,
    on_main_worktree: bool = True,
    proposal_id_seed: str | None = None,
) -> ProposeResult:
    store_root = store_root.resolve()
    mode_enum = parse_mode(mode.value if isinstance(mode, Mode) else str(mode))
    assert_mode_allowed(mode_enum)

    proposal_id = make_proposal_id(
        source_product=source_product,
        bug_class=bug_class,
        seed=proposal_id_seed,
    )

    if not classify.should_propose:
        result = ProposeResult(
            proposal_id=proposal_id,
            mode=mode_enum.value,
            classification=classify.classification.value,
            declined=True,
            rationale=classify.rationale,
            proposal_path=None,
            block_names=list(classify.block_names),
        )
        if mode_enum is Mode.DRY_RUN:
            return result
        # Still record a decline artifact for auditability (proposal package only).
        out_dir = proposal_dir_for(store_root, proposal_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        decline = out_dir / "DECLINED.md"
        decline.write_text(
            f"# Declined\n\n"
            f"- Classification: `{classify.classification.value}`\n"
            f"- Rationale: {classify.rationale}\n"
            f"- Source: {source_product} / {source_ref}\n"
            f"- No store mutation proposed.\n",
            encoding="utf-8",
        )
        summary = out_dir / "summary.json"
        summary.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
        written = [decline, summary]
        assert_writes_scoped(store_root, written, on_main_worktree=on_main_worktree)
        result.proposal_path = str(out_dir)
        result.artifacts = [str(p.relative_to(store_root)).replace("\\", "/") for p in written]
        summary.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
        return result

    # Block-level path
    if mode_enum is Mode.DRY_RUN:
        migrations = propose_migration(
            store_root=store_root,
            classify=classify,
            product_diff=product_diff,
            bug_class=bug_class,
            source_product=source_product,
        )
        fanouts = [fanout_for_block(store_root, b) for b in classify.block_names]
        flagged = sorted({p for f in fanouts for p in f.flagged_products})
        return ProposeResult(
            proposal_id=proposal_id,
            mode=mode_enum.value,
            classification=classify.classification.value,
            declined=False,
            rationale=classify.rationale,
            proposal_path=None,
            block_names=list(classify.block_names),
            fanout_products=flagged,
            artifacts=[f"(dry-run) migrate {m.block_name}" for m in migrations],
        )

    out_dir = proposal_dir_for(store_root, proposal_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    (out_dir / "classification.json").write_text(
        json.dumps(
            {
                "classification": classify.classification.value,
                "block_names": list(classify.block_names),
                "block_paths": list(classify.block_paths),
                "platform_paths": list(classify.platform_paths),
                "touched_paths": list(classify.touched_paths),
                "rationale": classify.rationale,
                "reasons": list(classify.reasons),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    written.append(out_dir / "classification.json")

    migrations = propose_migration(
        store_root=store_root,
        classify=classify,
        product_diff=product_diff,
        bug_class=bug_class,
        source_product=source_product,
    )
    if not migrations:
        raise GuardrailViolation(
            "Block-level classification but no migratable store target — aborting."
        )
    written.extend(write_migration_artifacts(out_dir, migrations))

    tests_added: list[str] = []
    all_flagged: list[str] = []
    for block_name in classify.block_names:
        test_paths = write_test_artifacts(
            out_dir,
            block_name=block_name,
            bug_class=bug_class,
            source_product=source_product,
            proposal_id=proposal_id,
        )
        written.extend(test_paths)
        tests_added.extend(p.name for p in test_paths if p.suffix == ".py")
        report = fanout_for_block(store_root, block_name)
        written.append(write_fanout_report(out_dir, report))
        all_flagged.extend(report.flagged_products)

    flagged = sorted(set(all_flagged))
    primary_block = classify.block_names[0]
    ledger_entry = LedgerEntry(
        bug_class=bug_class,
        found_on_product=source_product,
        extinct_across_products=tuple(flagged),
        pinned_by_tests=tuple(tests_added),
        block_name=primary_block,
        proposal_id=proposal_id,
        source_ref=source_ref,
        status="proposed",
    )
    written.append(draft_ledger_entry_file(out_dir, ledger_entry))

    payload = build_pr_payload(
        proposal_id=proposal_id,
        block_names=list(classify.block_names),
        classification=classify.classification.value,
        source_product=source_product,
        source_ref=source_ref,
        tests_added=tests_added,
        fanout_products=flagged,
        ledger_draft_summary=f"Bug class `{bug_class}` extinct across: {', '.join(flagged) or 'TBD'}",
        mode=mode_enum.value,
    )
    written.append(write_pr_payload(out_dir, payload))

    assert_writes_scoped(store_root, written, on_main_worktree=on_main_worktree)

    pr_result = None
    if open_pr:
        # Still dry-run gh by default unless LIVE (which is gated off).
        pr_result = create_pr(payload, dry_run=(mode_enum is not Mode.LIVE))

    result = ProposeResult(
        proposal_id=proposal_id,
        mode=mode_enum.value,
        classification=classify.classification.value,
        declined=False,
        rationale=classify.rationale,
        proposal_path=str(out_dir),
        block_names=list(classify.block_names),
        artifacts=[str(p.relative_to(store_root)).replace("\\", "/") for p in written],
        pr_payload=payload.to_dict(),
        pr_create_result=pr_result,
        fanout_products=flagged,
    )
    summary = out_dir / "summary.json"
    summary.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return result


def propose_from_diff_text(
    store_root: Path,
    diff_text: str,
    *,
    source_product: str,
    bug_class: str,
    source_ref: str = "",
    mode: Mode | str = Mode.PROPOSE,
    open_pr: bool = False,
) -> ProposeResult:
    classify = filter_known_blocks(classify_diff(diff_text), store_root)
    return run_propose(
        store_root=store_root,
        classify=classify,
        product_diff=diff_text,
        source_product=source_product,
        bug_class=bug_class,
        source_ref=source_ref or "stdin-diff",
        mode=mode,
        open_pr=open_pr,
        proposal_id_seed=diff_text,
    )
