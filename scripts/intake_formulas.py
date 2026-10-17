#!/usr/bin/env python3
"""The front door for encoded figures. No source, no encode.

The composition audit checks kits that already exist. This is the gate a
figure passes on the way IN, which is the only point where refusing is
cheap -- once a rate is in a shipped kit and an engine reads it, removing it
is a migration.

Two rules, enforced rather than remembered:

  1. A submission declares where its figures came from, or it is refused.
  2. contributor_unverified figures are PARKED -- written outside the kit's
     declared data, so nothing loads them -- until someone verifies them.
     Parking is a real location, not a flag someone has to honour.

Usage:
    python scripts/intake_formulas.py --kit insurance --file rates.json \\
        --kind regulator --reference "HKIA GL16/GN16 s3.2"

    python scripts/intake_formulas.py --kit medical --file sheet.json \\
        --kind contributor_unverified --reference "filled sheet from D."
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from audit_kit_composition import (  # noqa: E402
    KITS_DIR,
    MODULES_DIR,
    REGISTRY_DIR,
    SOURCE_KINDS,
    _dirs,
    _modules,
    audit_kit,
    load_known,
)

UNVERIFIED = "contributor_unverified"
PARKED_DIR = "parked"
DATA_REL = os.path.join("app", "data")


def _kit_root(kit):
    return os.path.join(KITS_DIR, kit)


def _bundle_or_root(kit):
    """Published kits carry data under bundle/; unpublished at the root."""
    bundle = os.path.join(_kit_root(kit), "bundle")
    return bundle if os.path.isdir(bundle) else _kit_root(kit)


def stamp_provenance(payload, *, kind, reference, recorded_on):
    """Attach the record. Never overwrites one that is already there.

    A submission that already carries per-item citations keeps them; the
    file-level record is added beside them, not on top.
    """
    if not isinstance(payload, dict):
        raise ValueError("a formula file must be a JSON object at the top level")
    if "provenance" in payload:
        raise ValueError(
            "this file already declares provenance; edit it directly rather "
            "than re-stamping, so an existing record is never silently replaced"
        )
    out = dict(payload)
    record = {"kind": kind, "recorded_on": recorded_on}
    if reference:
        record["reference"] = reference
    if kind == UNVERIFIED:
        record["parked"] = True
    out["provenance"] = record
    return out


def intake(kit, src_path, *, kind, reference, today=None):
    """Returns (destination, declared_in_manifest, messages)."""
    messages = []
    if kind not in SOURCE_KINDS:
        raise ValueError(
            "unknown source kind %r; one of: %s" % (kind, ", ".join(SOURCE_KINDS))
        )
    if kind != UNVERIFIED and not (reference or "").strip():
        # "regulator" with no citation is an assertion, not a source.
        raise ValueError(
            "kind=%s requires --reference naming the document or dataset; a "
            "source kind with nothing to check is not a source" % kind
        )
    if not os.path.isdir(_kit_root(kit)):
        raise ValueError("no kit at %s" % _kit_root(kit))
    if not os.path.isfile(src_path):
        raise ValueError("no such file: %s" % src_path)

    payload = json.loads(open(src_path, encoding="utf-8").read())
    stamped = stamp_provenance(
        payload,
        kind=kind,
        reference=reference,
        recorded_on=(today or date.today().isoformat()),
    )

    name = os.path.basename(src_path)

    if kind == UNVERIFIED:
        # Parked OUTSIDE the declared data set. Nothing loads it, because
        # nothing is told it exists. That is the difference between parking
        # a figure and labelling it.
        dest_dir = os.path.join(_kit_root(kit), PARKED_DIR)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, name)
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(stamped, fh, indent=2)
            fh.write("\n")
        messages.append(
            "PARKED at %s. Not added to the manifest, so no engine can load "
            "it. Verify it and re-run with a checkable --kind to ship it."
            % os.path.relpath(dest)
        )
        return dest, False, messages

    dest_dir = os.path.join(_bundle_or_root(kit), DATA_REL)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(stamped, fh, indent=2)
        fh.write("\n")

    rel = os.path.join(DATA_REL, name).replace(os.sep, "/")
    manifest_path = os.path.join(_kit_root(kit), "manifest.json")
    manifest = json.loads(open(manifest_path, encoding="utf-8").read())
    declared = manifest.setdefault("data", [])
    if rel not in declared:
        declared.append(rel)
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
            fh.write("\n")
        messages.append("declared in manifest data: %s" % rel)

    messages.append("encoded at %s (%s)" % (os.path.relpath(dest), kind))
    return dest, True, messages


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kit", required=True)
    parser.add_argument("--file", required=True, dest="path")
    parser.add_argument("--kind", required=True, choices=list(SOURCE_KINDS))
    parser.add_argument("--reference", default="")
    args = parser.parse_args(argv)

    try:
        _dest, _declared, messages = intake(
            args.kit, args.path, kind=args.kind, reference=args.reference
        )
    except (ValueError, OSError) as exc:
        sys.stdout.write("REFUSED: %s\n" % exc)
        return 1

    for line in messages:
        sys.stdout.write(line + "\n")

    # Same gate the publish path runs: a figure that just landed must leave
    # the kit in a state the audit accepts.
    known_blocks = _dirs(REGISTRY_DIR) | _modules(MODULES_DIR)
    registered = load_known()
    findings = [
        (c, d)
        for c, d in audit_kit(args.kit, KITS_DIR, known_blocks)
        if "%s :: %s" % (args.kit, c) not in registered
    ]
    if findings:
        sys.stdout.write("\nCOMPOSITION FINDINGS after intake:\n")
        for code, detail in findings:
            sys.stdout.write("  %s: %s\n" % (code, detail))
        return 1
    sys.stdout.write("Composition audit: clean.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
