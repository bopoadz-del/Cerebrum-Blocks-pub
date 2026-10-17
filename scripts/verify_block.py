#!/usr/bin/env python3
"""Verify the publisher signature and file integrity of a block folder."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root so app imports work when run from scripts/.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.publisher_registry import BlockVerifier, PublisherRegistry

# Imported lazily so the script can still run a basic signature check even if
# the validation gate pulls in optional dependencies.


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a block folder's signature and digests."
    )
    parser.add_argument("--block", required=True, type=Path, help="Path to block folder")
    parser.add_argument(
        "--publisher",
        help="Expected publisher ID (optional; verifies manifest matches if provided)",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=None,
        help="Override path to publishers.json",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run the full validation gate (signature + AST + manifest) instead of signature only",
    )
    parser.add_argument(
        "--certifications",
        type=Path,
        default=None,
        help="Override path to block_certifications.json (used with --validate)",
    )
    args = parser.parse_args()

    block_path = Path(args.block)
    registry = PublisherRegistry(path=args.registry)

    if args.validate:
        from app.core.block_validation import BlockValidator

        validator = BlockValidator(
            publisher_registry=registry,
            certification_store_path=args.certifications,
        )
        result = validator.validate_block(
            block_path=block_path,
            publisher_id=args.publisher,
        )
        output = {
            "block_id": result.block_id,
            "version": result.version,
            "publisher_id": result.publisher_id,
            "status": result.status,
            "reasons": result.reasons,
            "certified_at": result.certified_at,
            "expires_at": result.expires_at,
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0 if result.status == "passed" else 1

    verifier = BlockVerifier(registry=registry)
    result = verifier.verify_block(
        block_path=block_path,
        publisher_id=args.publisher,
    )

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
