"""CLI entry: python -m carry_back ..."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from carry_back import LIVE_ENABLED, __version__
from carry_back.classify import classify_diff, classify_fixture_dir, filter_known_blocks
from carry_back.modes import Mode, parse_mode
from carry_back.propose import propose_from_diff_text, propose_from_fixture


def _store_root() -> Path:
    # carry_back/ lives at store repo root
    return Path(__file__).resolve().parent.parent


def cmd_classify(args: argparse.Namespace) -> int:
    root = Path(args.store_root).resolve() if args.store_root else _store_root()
    if args.fixture:
        result = filter_known_blocks(
            classify_fixture_dir(Path(args.fixture)), root
        )
    elif args.diff:
        text = Path(args.diff).read_text(encoding="utf-8")
        result = filter_known_blocks(classify_diff(text), root)
    else:
        print("Provide --fixture or --diff", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "classification": result.classification.value,
                "block_names": list(result.block_names),
                "rationale": result.rationale,
                "should_propose": result.should_propose,
                "reasons": list(result.reasons),
            },
            indent=2,
        )
    )
    return 0


def cmd_propose(args: argparse.Namespace) -> int:
    root = Path(args.store_root).resolve() if args.store_root else _store_root()
    mode = parse_mode(args.mode)
    if args.fixture:
        result = propose_from_fixture(
            root,
            Path(args.fixture),
            mode=mode,
            open_pr=args.open_pr,
        )
    elif args.diff:
        result = propose_from_diff_text(
            root,
            Path(args.diff).read_text(encoding="utf-8"),
            source_product=args.source_product or "unknown-product",
            bug_class=args.bug_class or "unspecified-bug-class",
            source_ref=args.source_ref or args.diff,
            mode=mode,
            open_pr=args.open_pr,
        )
    else:
        print("Provide --fixture or --diff", file=sys.stderr)
        return 2
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if (result.declined or result.proposal_path) else 1


def cmd_status(_: argparse.Namespace) -> int:
    print(
        json.dumps(
            {
                "version": __version__,
                "live_enabled": LIVE_ENABLED,
                "live_status": "NOT LIVE" if not LIVE_ENABLED else "LIVE",
                "modes": [m.value for m in Mode],
                "gate": (
                    "LIVE requires one demonstrated block-level migration AND "
                    "one correct platform-specific decline, then flip LIVE_ENABLED."
                ),
            },
            indent=2,
        )
    )
    return 0


def cmd_self_test(args: argparse.Namespace) -> int:
    """Run acceptance fixtures end-to-end (used by pytest and operators)."""
    root = Path(args.store_root).resolve() if args.store_root else _store_root()
    fixtures = root / "fixtures" / "carry_back"
    if not fixtures.is_dir():
        # the seeded fixtures are generated at run time, never committed
        from carry_back.seeds import seed_dir

        fixtures = seed_dir()
    block_fix = fixtures / "block_level_fix"
    platform_fix = fixtures / "platform_specific_fix"
    errors: list[str] = []

    if not block_fix.is_dir() or not platform_fix.is_dir():
        print("Fixtures missing under fixtures/carry_back/", file=sys.stderr)
        return 1

    migrate = propose_from_fixture(root, block_fix, mode=Mode.PROPOSE, open_pr=True)
    if migrate.declined:
        errors.append("block_level_fix incorrectly declined")
    if not migrate.pr_payload:
        errors.append("block_level_fix missing pr_payload")
    else:
        arts = set(migrate.artifacts)
        needed = ("migrate_", "test_pin_", "test_seam_stub_", "ledger_entry.md", "fanout.md")
        for token in needed:
            if not any(token in a for a in arts):
                errors.append(f"block_level_fix missing artifact containing {token!r}")

    decline = propose_from_fixture(root, platform_fix, mode=Mode.PROPOSE)
    if not decline.declined:
        errors.append("platform_specific_fix should decline")
    if decline.classification not in {
        "platform_specific",
        "declined_ambiguous",
        "needs_human_classification",
    }:
        errors.append(f"unexpected decline class: {decline.classification}")

    from carry_back import LIVE_ENABLED

    if LIVE_ENABLED:
        errors.append("LIVE_ENABLED must remain False until gate satisfied")

    payload = {
        "ok": not errors,
        "errors": errors,
        "migrate_proposal_id": migrate.proposal_id,
        "decline_proposal_id": decline.proposal_id,
        "live_status": "NOT LIVE",
    }
    print(json.dumps(payload, indent=2))
    return 0 if not errors else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="carry_back",
        description="Carry-Back Agent — propose store migrations (never silent mutate).",
    )
    parser.add_argument("--version", action="version", version=f"carry_back {__version__}")
    parser.add_argument(
        "--store-root",
        default=None,
        help="Store repo root (default: parent of carry_back package)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="Show LIVE gate / version")
    p_status.set_defaults(func=cmd_status)

    p_cls = sub.add_parser("classify", help="Classify a product fix")
    p_cls.add_argument("--fixture", help="Fixture directory")
    p_cls.add_argument("--diff", help="Unified diff file")
    p_cls.set_defaults(func=cmd_classify)

    p_prop = sub.add_parser("propose", help="Classify and write a proposal package")
    p_prop.add_argument("--fixture", help="Fixture directory under fixtures/carry_back/")
    p_prop.add_argument("--diff", help="Unified diff file from a product")
    p_prop.add_argument("--source-product", default=None)
    p_prop.add_argument("--bug-class", default=None)
    p_prop.add_argument("--source-ref", default=None)
    p_prop.add_argument(
        "--mode",
        default=Mode.PROPOSE.value,
        choices=[m.value for m in Mode],
        help="dry-run | propose | live (live gated)",
    )
    p_prop.add_argument(
        "--open-pr",
        action="store_true",
        help="Build/create PR payload (gh dry-run unless LIVE)",
    )
    p_prop.set_defaults(func=cmd_propose)

    p_st = sub.add_parser("self-test", help="Run seeded acceptance fixtures")
    p_st.set_defaults(func=cmd_self_test)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
