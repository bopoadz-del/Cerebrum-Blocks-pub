#!/usr/bin/env python3
"""Static composition check for every kit in block_store/kits/.

Silence is not permission. A kit that lists eighteen blocks and says nothing
about how they compose is not a kit that "has no ordering constraints" -- it
is a kit whose ordering constraints were never written down. This audit
refuses to read an absent declaration as an empty one.

Pure static analysis: reads JSON and directory listings. No database, no
Redis, no imports of block code. Safe to run in CI and as a publish gate.

Exit 1 if any finding is unregistered, mirroring scripts/audit_stubs.py:
implement it, or register it in KNOWN_KIT_GAPS.md so the gap is visible.
"""
from __future__ import annotations

import json
import os
import sys

KITS_DIR = os.path.join("block_store", "kits")
REGISTRY_DIR = "block_registry"
MODULES_DIR = os.path.join("app", "blocks")
KNOWN_FILE = "KNOWN_KIT_GAPS.md"

# A template manifest carries {{placeholders}} and therefore cannot be valid
# JSON. It is skipped by name -- never by "failed to parse", which would also
# skip a real kit whose manifest someone broke.
TEMPLATE_KIT = "_template"

REQUIRED_KEYS = ("id", "name", "version", "description", "status", "blocks")

# Recognised spellings of a composition declaration. "waves" predates this
# audit (universal_kernel uses it) and is accepted rather than migrated:
# inventing a second key for the same idea would leave two half-truths.
COMPOSITION_KEYS = ("flow", "waves")

# Not every kit is a pipeline. The 6-block domain kits ship a BUNDLE of
# capabilities whose container resolves a single block; there is no ordering
# to write down, and demanding a flow of them would invite a fabricated one.
#
# Declaring this is still required. "silence is not permission" is about the
# difference between a kit that says its blocks are independent and a kit
# that says nothing -- the first is a decision, the second is an omission,
# and only the author can tell them apart.
INDEPENDENT = "independent"

# Where an encoded figure came from. A rate, threshold or limit with no
# recorded origin is not "probably fine" -- it is a number nobody can check.
#   regulator             published rule from a supervisory authority
#   spc                   statistical process control / measured data
#   internal_protocol     the operator's own documented procedure
#   contributor_unverified supplied by a contributor, not yet checked
SOURCE_KINDS = ("regulator", "spc", "internal_protocol", "contributor_unverified")

# Accepted spellings of a provenance record. "citation" predates this audit
# (gn16_ruleset.json carries one on all 12 of its rules) and is accepted for
# the same reason "waves" is.
PROVENANCE_KEYS = ("provenance", "source", "citation")


def load_known():
    """Registered gaps, one per '- kit :: code' line, same shape as
    audit_stubs.py's KNOWN_INCOMPLETE.md."""
    if not os.path.exists(KNOWN_FILE):
        return set()
    out = set()
    for line in open(KNOWN_FILE, encoding="utf-8", errors="ignore"):
        line = line.strip()
        if line.startswith("- ") and "::" in line:
            out.add(line[2:].split("  ")[0].strip())
    return out


def _dirs(path):
    if not os.path.isdir(path):
        return set()
    return {n for n in os.listdir(path) if os.path.isdir(os.path.join(path, n))}


def _modules(path):
    if not os.path.isdir(path):
        return set()
    return {n[:-3] for n in os.listdir(path) if n.endswith(".py")}


def _composition_blocks(manifest):
    """Flatten a composition declaration to the blocks it orders.

    Accepts a list of stages (``[[a, b], [c]]``), a mapping of stage name to
    blocks (``{"wave1": [...]}``), or a flat list.
    """
    for key in COMPOSITION_KEYS:
        if key not in manifest:
            continue
        val = manifest[key]
        # An explicit "these do not compose" is a declaration, not silence.
        if isinstance(val, str) and val.strip().lower() == INDEPENDENT:
            return key, None
        if isinstance(val, dict):
            out = []
            for stage in val.values():
                out.extend(stage if isinstance(stage, list) else [stage])
            return key, out
        if isinstance(val, list):
            out = []
            for item in val:
                out.extend(item if isinstance(item, list) else [item])
            return key, out
        return key, []
    return None, None


def _has_record(obj):
    """Does this mapping carry a non-empty provenance record?"""
    if not isinstance(obj, dict):
        return False
    for key in PROVENANCE_KEYS:
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return True
        if isinstance(val, dict) and val:
            return True
    return False


# Collections that ARE the provenance. Requiring each entry of a "sources"
# list to cite its own source is circular.
_SOURCE_COLLECTIONS = frozenset({"sources", "references", "citations", "bibliography"})


def _every_item_cited(data):
    """gn16_ruleset.json records provenance per rule rather than per file.

    EVERY collection of mappings must be fully cited, not merely one of them.
    An earlier version passed a file if any single collection was cited,
    which let hkia_gn16_corpus.json through on its 8/8 section_summaries
    while its sources collection was 0/2 -- a document can always be made to
    pass by adding one well-cited list beside the uncited figures.

    11 of 12 cited is not a cited document either; it is a document with an
    uncited rule in it.
    """
    seen = False
    for key, val in data.items():
        if key in _SOURCE_COLLECTIONS:
            continue
        items = list(val.values()) if isinstance(val, dict) else val
        if not isinstance(items, (list, tuple)):
            continue
        items = list(items)
        mappings = [i for i in items if isinstance(i, dict)]
        if not mappings or len(mappings) != len(items):
            continue
        seen = True
        if not all(_has_record(i) for i in mappings):
            return False
    return seen


def _provenance_findings(kit, kits_dir, manifest):
    """Every declared data file must say where its figures came from."""
    findings = []
    declared = manifest.get("data")
    if not isinstance(declared, list):
        return findings

    # Published kits carry their data under bundle/; a kit that has not been
    # published yet carries it at the kit root.
    roots = [
        os.path.join(kits_dir, kit, "bundle"),
        os.path.join(kits_dir, kit),
    ]

    for rel in declared:
        if not isinstance(rel, str):
            continue
        # A manifest may declare a directory ("schemas/"); its presence is
        # what is checked, not its contents.
        path = next(
            (os.path.join(r, rel) for r in roots if os.path.exists(os.path.join(r, rel))),
            None,
        )
        if path is None:
            findings.append(("data_file_missing", "declared but not on disk: %s" % rel))
            continue
        if os.path.isdir(path) or not rel.endswith(".json"):
            continue
        try:
            data = json.loads(open(path, encoding="utf-8").read())
        except (ValueError, OSError) as exc:
            findings.append(("data_unparseable", "%s: %s" % (rel, str(exc)[:80])))
            continue
        if not isinstance(data, dict):
            continue

        record = None
        for key in ("provenance", "source"):
            if isinstance(data.get(key), dict):
                record = data[key]
                break

        if record is None:
            if not (_has_record(data) or _every_item_cited(data)):
                findings.append(
                    (
                        "data_provenance_missing",
                        "%s records no source for its figures" % rel,
                    )
                )
            continue

        kind = record.get("kind")
        if kind not in SOURCE_KINDS:
            findings.append(
                ("data_provenance_kind_unknown", "%s: kind=%r" % (rel, kind))
            )
            continue
        if kind != "contributor_unverified" and not str(record.get("reference", "")).strip():
            findings.append(
                ("data_provenance_unreferenced", "%s: kind=%s with no reference" % (rel, kind))
            )
        if kind == "contributor_unverified" and record.get("parked") is not True:
            # The intake rule, enforced rather than remembered: unverified
            # figures are parked, never shipped.
            findings.append(
                (
                    "data_unverified_not_parked",
                    "%s carries contributor_unverified figures without parked: true" % rel,
                )
            )
    return findings


def audit_kit(kit, kits_dir, known_blocks):
    """Return a list of (code, detail) findings for one kit."""
    findings = []
    path = os.path.join(kits_dir, kit, "manifest.json")
    if not os.path.isfile(path):
        return [("no_manifest", "block_store/kits/%s/manifest.json missing" % kit)]

    try:
        manifest = json.loads(open(path, encoding="utf-8").read())
    except (ValueError, OSError) as exc:
        return [("manifest_unparseable", str(exc)[:120])]

    for key in REQUIRED_KEYS:
        if key not in manifest:
            findings.append(("missing_key", "required key %r absent" % key))

    if manifest.get("id") not in (None, kit):
        findings.append(
            ("id_mismatch", "manifest id %r != directory %r" % (manifest.get("id"), kit))
        )

    blocks = manifest.get("blocks")
    if not isinstance(blocks, list):
        return findings + [("blocks_not_a_list", "blocks is %s" % type(blocks).__name__)]

    dupes = sorted({b for b in blocks if blocks.count(b) > 1})
    if dupes:
        findings.append(("duplicate_blocks", ", ".join(dupes)))

    # A kit may vendor its own blocks (universal_kernel/wave1/...), so the
    # kit's own subdirectories count as a resolution path.
    local = set()
    kit_root = os.path.join(kits_dir, kit)
    for entry in sorted(_dirs(kit_root)):
        local |= _dirs(os.path.join(kit_root, entry))
    # Kit-first blocks ship as bundle/app/blocks/<name>.py once published,
    # or app/blocks/<name>.py before that. The waveN/<name>/ walk above only
    # sees directories two levels down, so a module in the bundle layout
    # would otherwise look unresolved even though it is on disk.
    for root in (os.path.join(kit_root, "bundle"), kit_root):
        blocks_dir = os.path.join(root, "app", "blocks")
        local |= _modules(blocks_dir)
        local |= _dirs(blocks_dir)
    resolvable = known_blocks | local

    unresolved = [b for b in blocks if b not in resolvable]
    if unresolved:
        findings.append(("unresolved_block", ", ".join(unresolved)))

    comp_key, ordered = _composition_blocks(manifest)
    if comp_key is None:
        if len(blocks) > 1:
            findings.append(
                (
                    "no_composition",
                    "%d blocks, no %s declaration -- ordering was never stated, "
                    "not stated to be unconstrained"
                    % (len(blocks), "/".join(COMPOSITION_KEYS)),
                )
            )
    elif ordered is None:
        pass  # declared independent; there is no ordering to agree with
    else:
        uncovered = [b for b in blocks if b not in set(ordered)]
        if uncovered:
            findings.append(
                ("composition_incomplete", "%s omits: %s" % (comp_key, ", ".join(uncovered)))
            )
        extra = [b for b in ordered if b not in set(blocks)]
        if extra:
            findings.append(
                ("composition_unknown_block", "%s orders non-member: %s" % (comp_key, ", ".join(extra)))
            )

    findings.extend(_provenance_findings(kit, kits_dir, manifest))
    return findings


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not os.path.isdir(KITS_DIR):
        sys.stdout.write("no %s directory; nothing to audit\n" % KITS_DIR)
        return 0

    known_blocks = _dirs(REGISTRY_DIR) | _modules(MODULES_DIR)
    known_gaps = load_known()

    unregistered = []
    registered = 0
    audited = 0

    for kit in sorted(os.listdir(KITS_DIR)):
        if not os.path.isdir(os.path.join(KITS_DIR, kit)):
            continue
        if kit == TEMPLATE_KIT:
            continue
        audited += 1
        for code, detail in audit_kit(kit, KITS_DIR, known_blocks):
            key = "%s :: %s" % (kit, code)
            if key in known_gaps:
                registered += 1
                continue
            unregistered.append((key, detail))

    if unregistered:
        sys.stdout.write("KIT COMPOSITION FINDINGS (fix or register in %s):\n" % KNOWN_FILE)
        for key, detail in unregistered:
            sys.stdout.write("  %s\n      %s\n" % (key, detail))
        sys.stdout.write(
            "TOTAL: %d unregistered across %d kits (%d registered)\n"
            % (len(unregistered), audited, registered)
        )
        return 1

    sys.stdout.write(
        "KIT COMPOSITION OK: %d kits audited, %d registered gap(s).\n" % (audited, registered)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
