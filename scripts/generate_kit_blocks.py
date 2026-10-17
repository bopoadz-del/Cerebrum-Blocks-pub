#!/usr/bin/env python3
"""Generate the Store plumbing for every declarative reasoning kit.

A kit is a DECLARATION -- ``app/blocks/<kit>/manifest.yaml`` (vocabulary) plus
``invariants.yaml`` (records). Everything else a kit needs to be a published,
certified Store block is mechanical, so it is generated rather than hand-written
seventeen times:

  app/blocks/<kit>_kit.py                 identity only; no domain logic
  block_registry/<kit>_kit/block.json     manifest, acceptance list from the
                                          kit's own invariants
  block_registry/<kit>_kit/block.py       the standard adapter
  block_registry/<kit>_kit/Dockerfile     copied from the reference block

The block id is `<kit>_kit`, deliberately NOT `<kit>_reasoning`: five kits already
publish a `<kit>_reasoning` block built on a hand-written gate, three of them
signed. The declarative kit is ADDED beside them, never over them.
  block_certifications.json                    entry against `process`

Idempotent, and it never overwrites a signature: `block.json` keeps any
`signature` and `digests` already present, because re-signing on every run would
make the signature meaningless. Run it again whenever a kit is added.

    python scripts/generate_kit_blocks.py            # write
    python scripts/generate_kit_blocks.py --check    # report drift, write nothing
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
BLOCKS = ROOT / "app" / "blocks"
REGISTRY = ROOT / "block_registry"
CERTS = ROOT / "block_certifications.json"
REFERENCE_DOCKERFILE = REGISTRY / "datacentre_reasoning" / "Dockerfile"

ADAPTER = '''#!/usr/bin/env python3
"""
Adapter for Cerebrum block: {block_id}
"""

import asyncio

from app.blocks.{kit}_kit import {cls}


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    """Execute the {block_id} block."""
    instance = {cls}()
    input_data = kwargs.get("input", kwargs)
    params = {{k: v for k, v in kwargs.items() if k != "input"}}
    envelope = _run_async(instance.process(input_data, params))
    if envelope.get("status") in ("error", "refused"):
        raise RuntimeError(envelope.get("error") or "{block_id} block failed")
    return envelope.get("result", envelope)
'''

INPUTS = [
    {"name": "question", "type": "string", "required": False,
     "description": "the operator question, classified at H0 BEFORE any retrieval"},
    {"name": "figures", "type": "array", "required": False,
     "description": "figures to gate: quantity, value, unit, origin, source_id, "
                    "source_class, revision, qualifiers, claim_class, derivations, "
                    "conditions, steps, bounds, asked_about, span, text"},
    {"name": "state", "type": "json", "required": False,
     "description": "state records by provider name, each {as_of: <epoch>}; an "
                    "absent provider yields UNKNOWN, never a design-basis fallback"},
    {"name": "events", "type": "array", "required": False,
     "description": "events that have happened, matched against the kit's "
                    "staleness_triggers"},
    {"name": "hooks", "type": "array", "required": False,
     "description": "subset of H0..H4 to run; all five by default, because a "
                    "partial sweep is a silent coverage gap"},
]

OUTPUTS = [
    {"name": "verdict", "type": "json",
     "description": "pass | annotated | flagged | refused, with findings, "
                    "blocked_reason, hooks_run, retrieval_permitted, "
                    "interview_status, unfilled_figures, unmeasured_invariants, "
                    "ships and kit_disabled"},
]


def kits() -> list:
    return sorted(
        p.parent.name for p in BLOCKS.glob("*/manifest.yaml")
        if (p.parent / "invariants.yaml").is_file()
    )


def class_name(kit: str) -> str:
    return "".join(part.capitalize() for part in kit.split("_")) + "KitBlock"


def acceptance_from(invariants: list) -> list:
    """The kit's own records ARE its acceptance list -- one entry each, naming the
    kind, the hook and what it refuses. A hand-kept second list would drift."""
    out = []
    for inv in invariants:
        hook = inv.get("hook") or "per the routing map"
        out.append({
            "id": str(inv["id"]).lower().replace("-", "_"),
            "check": f"{inv['id']} ({inv['kind']} at {hook}, severity "
                     f"{inv['severity']}): {inv.get('message') or 'enforced'}",
            "status": _acceptance_status(inv),
        })
    return out


#: Invariant severity -> the BlockResult status the block surfaces for it.
#:
#: An invariant severity and a BlockResult status are two different vocabularies,
#: and this used to pass any non-`refuse` severity straight through:
#: `"refused" if severity == "refuse" else severity`. So nine `flag` invariants
#: across five kits wrote `status: "flag"` into their signed block.json, which is
#: not a BlockResult status, and the Lane 2 contract test rejected all five.
#:
#: `ok` is deliberately absent from the values: the contract also rejects an
#: acceptance criterion claiming `ok`, because a fail-loud check that reports a
#: pass proves nothing happened.
_SEVERITY_TO_STATUS = {
    "refuse": "refused",   # the answer is blocked outright
    "flag": "partial",     # the answer stands, carrying a caveat the caller must see
}


def _acceptance_status(inv: dict) -> str:
    """The BlockResult status for one invariant, or a loud failure.

    Raises rather than passing an unmapped severity through. Passing it through is
    exactly how `flag` reached five signed manifests: the generator was silent, the
    signature was valid, and the contract test found it in CI.
    """
    severity = str(inv.get("severity") or "")
    try:
        return _SEVERITY_TO_STATUS[severity]
    except KeyError:
        raise SystemExit(
            f"{inv.get('id')}: severity {severity!r} has no BlockResult status. Add it "
            f"to _SEVERITY_TO_STATUS in this script — do not let it reach block.json, "
            f"where it validates as a signature and fails as a contract."
        ) from None


def build(kit: str, check_only: bool = False) -> list:
    changes = []
    manifest = yaml.safe_load((BLOCKS / kit / "manifest.yaml").read_text(encoding="utf-8"))
    records = yaml.safe_load((BLOCKS / kit / "invariants.yaml").read_text(encoding="utf-8"))
    invariants = (records or {}).get("invariants") or []
    # `<kit>_kit`, never `<kit>_reasoning`. Five kits already publish a
    # `<kit>_reasoning` block built on a hand-written gate, three of them SIGNED.
    # An earlier version of this script used that id and overwrote them --
    # replacing a published, signed block instead of adding a new one beside it.
    block_id = f"{kit}_kit"
    cls = class_name(kit)

    folder = REGISTRY / block_id
    if not check_only:
        folder.mkdir(parents=True, exist_ok=True)

    # Dockerfile: copied verbatim from the reference block.
    dockerfile = folder / "Dockerfile"
    wanted = REFERENCE_DOCKERFILE.read_bytes()
    if not dockerfile.is_file() or dockerfile.read_bytes() != wanted:
        changes.append(f"{block_id}/Dockerfile")
        if not check_only:
            dockerfile.write_bytes(wanted)

    # Adapter.
    adapter = folder / "block.py"
    body = ADAPTER.format(block_id=block_id, kit=kit, cls=cls)
    if not adapter.is_file() or adapter.read_text(encoding="utf-8") != body:
        changes.append(f"{block_id}/block.py")
        if not check_only:
            adapter.write_text(body, encoding="utf-8")

    # block.json -- keeping any signature and digests already present.
    path = folder / "block.json"
    existing = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            existing = {}
    entry = {
        "acceptance": acceptance_from(invariants),
        "author": "Cerebrum Team",
        "description": (
            f"Declarative {kit.replace('_', ' ')} reasoning kit on the shared "
            f"reasoning layer. {len(invariants)} invariants declared in "
            f"app/blocks/{kit}/invariants.yaml across the kinds the portable spec "
            f"defines (grounding, qualifier, unit_discipline, authority, provenance, "
            f"currency, scope, derivation, band) and the five hooks (H0 "
            f"pre-retrieval, H1 ranking, H2 tool-time, H3 answer-time, H4 "
            f"export-time). Vocabulary in app/blocks/{kit}/manifest.yaml. Scope "
            f"refusals classify BEFORE retrieval. Fail closed: a kit that does not "
            f"parse is DISABLED and refuses every statement rather than passing them "
            f"through with no invariants. NO INTERVIEW HAS RUN, so every declared "
            f"figure value is null and the block refuses rather than inventing one "
            f"(app/blocks/{kit}/KNOWN_GAPS.md). Measured by "
            f"tests/blocks/test_reasoning_kits.py."
        ),
        "execution": {"image": f"ghcr.io/cerebrum-blocks/{block_id}:latest", "type": "docker"},
        "id": block_id,
        "inputs": INPUTS,
        "layer": 3,
        "name": block_id,
        "never": [],
        "outputs": OUTPUTS,
        "permissions": {"blocks": [], "filesystem": False, "imports": [], "network": False},
        "publisher_id": "cerebrum_platform",
        "reads": [{"kind": "caller", "scope": "input"}],
        "requires": [],
        "tags": sorted({kit.split("_")[0], "reasoning", "gate", "kit"}),
        "trust_tier": "platform",
        "version": "1.0.0",
        "writes": [{"kind": "caller", "scope": "output"}],
    }
    for keep in ("signature", "digests"):
        if keep in existing:
            entry[keep] = existing[keep]
    rendered = json.dumps(entry, indent=2, sort_keys=True) + "\n"
    if not path.is_file() or path.read_text(encoding="utf-8") != rendered:
        changes.append(f"{block_id}/block.json")
        if not check_only:
            path.write_text(rendered, encoding="utf-8")
    return changes


def certifications(check_only: bool = False) -> list:
    data = json.loads(CERTS.read_text(encoding="utf-8"))
    have = {b["block"]: b for b in data["blocks"]}
    added = []
    for kit in kits():
        block_id = f"{kit}_kit"
        entry = {
            "block": block_id,
            "module": f"app.blocks.{kit}_kit",
            "class": class_name(kit),
            "method": "process",
            "tests": ["tests/blocks/test_reasoning_kits.py"],
            "fixture": (
                f"app/blocks/{kit}/manifest.yaml and invariants.yaml - the kit's real "
                f"declaration on disk, loaded by process() through the shared "
                f"evaluator. The tests drive process() and assert what only a real "
                f"sweep produces: the H0 refusal returned BEFORE retrieval with "
                f"retrieval_permitted false, every declared scope pattern refusing "
                f"(each probe checked against its own pattern so a bad probe fails "
                f"rather than passes), all five hooks in hooks_run, an undeclared "
                f"qualifier refused by name, and the interview state travelling with "
                f"the answer."
            ),
            "include_in_ci": True,
        }
        current = have.get(block_id)
        if current != entry:
            added.append(block_id)
            if not check_only:
                if current is None:
                    data["blocks"].append(entry)
                else:
                    data["blocks"][data["blocks"].index(current)] = entry
    if added and not check_only:
        CERTS.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report drift, write nothing")
    args = parser.parse_args()

    names = kits()
    if not names:
        print("no declarative kits found", file=sys.stderr)
        return 1
    changed = []
    for kit in names:
        changed.extend(build(kit, args.check))
    certs = certifications(args.check)

    print(f"{len(names)} declarative kit(s): {', '.join(names)}")
    print(f"{len(changed)} registry file(s) {'would change' if args.check else 'written'}")
    for name in changed:
        print(f"  {name}")
    print(f"{len(certs)} certification entr(ies) {'would change' if args.check else 'written'}")
    for name in certs:
        print(f"  {name}")
    if args.check and (changed or certs):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
