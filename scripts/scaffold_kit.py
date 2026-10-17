#!/usr/bin/env python3
"""Stage K3 of the kit pipeline: a sourced intake in, a kit directory out.

WHAT IT EMITS
-------------
``block_store/kits/<kit>/`` from ``_template``, plus content derived only
from the intake:

* ``source_manifest.json`` -- one record per distinct (source, source_ref)
  the intake carried, so the kit's provenance is the sheet's provenance and
  can be diffed against it.
* ``app/data/domain_definitions.json`` -- the intake's formulas as a domain
  overlay. This is the exact path ``app/core/formula_definitions.py`` reads,
  so a formula that survived K1's source gate becomes a grounded definition
  in the generated product without a further step.
* ``prompts/`` and ``schemas/`` -- from the vocabulary, refusal-trap and
  entity items, verbatim.

WHAT IT REFUSES TO DECIDE
-------------------------
``status`` is ``draft``, never ``available``. A scaffolded kit has not had
its author pass (K4) or its evaluation written (K6); marking it installable
would put it on the shelf claiming a completeness nobody checked. That is the
automotive failure with the labels swapped.

``trust_tier`` is ``contributor_unverified``, which the Factory's compliance
gate does not accept. That is deliberate and not a bug: a kit scaffolded from
one contributor's sheet has had no reviewer, and the gate refusing to build
with it is the system working. A reviewer raises it in K4.

Formula ids are taken from the sheet, never coined. Where an item reads
``name = expression`` the split is mechanical and unambiguous; where it does
not, the definition is emitted with a null expression and listed as needing
the author. Guessing an expression would produce arithmetic nobody wrote,
carrying a real provenance record -- the worst combination available.

No ``overrides`` is ever emitted. Replacing a base definition is a deliberate
act requiring a stated reason under the precedence contract, and a scaffold
cannot supply one. Where an intake id collides with a base id, it is reported
so the author can decide; the kernel resolver would refuse it anyway.

Usage:
    python scripts/scaffold_kit.py --intake intake/dental.yaml
    python scripts/scaffold_kit.py --intake intake/dental.yaml --force

Exit codes:
    0  kit scaffolded, nothing needs the author's attention
    1  kit scaffolded, but items need attention (listed)
    2  usage error, or the kit directory already exists without --force
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KITS_DIR = PROJECT_ROOT / "block_store" / "kits"
TEMPLATE_DIR = KITS_DIR / "_template"

#: A freshly scaffolded kit is not installable. See the module docstring.
SCAFFOLD_STATUS = "draft"

#: No reviewer has seen this kit's content. The Factory gate refuses to build
#: with it until someone raises it, which is the point.
SCAFFOLD_TRUST_TIER = "contributor_unverified"

#: ``name = expression``. Anchored and single-``=`` so that a comparison or a
#: prose sentence containing an equals sign is not mistaken for a definition.
_DEFINITION_RE = re.compile(r"^\s*([A-Za-z][\w \-/%]*?)\s*=\s*([^=].*)$")

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: Names that appear in expressions but are operators/functions, not inputs.
_NOT_INPUTS = frozenset(
    {"and", "or", "not", "if", "else", "min", "max", "abs", "sum", "round"}
)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return slug


def pascal(domain: str) -> str:
    return "".join(part.title() for part in domain.split("_") if part)


# -- reading the intake ----------------------------------------------------


def load_intake(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    import yaml

    return yaml.safe_load(text)


def _provenance(item: Dict[str, Any]) -> Dict[str, Any]:
    """The item's own provenance, carried through unchanged.

    Every field here came out of K1's source gate, so it is the sheet's claim
    rather than this tool's. ``confidence`` stays null when the sheet stated
    none -- see intake_kit.
    """
    return {
        "kind": item.get("source", ""),
        "reference": item.get("source_ref", ""),
        "contributor_id": item.get("contributor_id", ""),
        "confidence": item.get("confidence"),
        "extracted_from": item.get("location", ""),
    }


# -- formulas --------------------------------------------------------------


def parse_definition(text: str) -> Tuple[Optional[str], Optional[str]]:
    """``"gross margin = (a - b) / a"`` -> ``("gross_margin", "(a - b) / a")``.

    Returns ``(None, None)`` when the item is not written as an assignment.
    The caller emits those with a null expression rather than inventing one.
    """
    match = _DEFINITION_RE.match(text)
    if not match:
        return None, None
    name, expression = match.group(1), match.group(2).strip()
    ident = slugify(name)
    if not ident or not expression:
        return None, None
    return ident, expression


def infer_inputs(expression: str) -> List[str]:
    """Identifiers the expression reads. Mechanical, not interpretive."""
    seen: List[str] = []
    for name in _IDENTIFIER_RE.findall(expression):
        if name.lower() in _NOT_INPUTS or name in seen:
            continue
        seen.append(name)
    return seen


def build_definitions(
    kit: str, formulas: List[Dict[str, Any]]
) -> Tuple[Dict[str, Any], List[str]]:
    """The domain overlay, plus items that need the author."""
    definitions: List[Dict[str, Any]] = []
    needs_author: List[str] = []
    used: Dict[str, str] = {}

    for item in formulas:
        text = item.get("text", "")
        ident, expression = parse_definition(text)
        if ident is None:
            ident = slugify(text)[:60] or f"unnamed_{len(definitions) + 1}"
            needs_author.append(
                f"{item.get('location', '?')}: not written as "
                f"'name = expression'; emitted with a null expression"
            )
        if ident in used:
            needs_author.append(
                f"{item.get('location', '?')}: id {ident!r} already defined by "
                f"{used[ident]}; the later one is emitted with a suffix"
            )
            suffix = 2
            while f"{ident}_{suffix}" in used:
                suffix += 1
            ident = f"{ident}_{suffix}"
        used[ident] = item.get("location", "?")

        entry: Dict[str, Any] = {
            "id": ident,
            "definition_version": 1,
            "key": f"{kit}:{ident}_v1",
            "tier": "domain-extension",
            "name": text if expression else text,
            "expression": expression,
            "inputs": infer_inputs(expression) if expression else [],
            "provenance": _provenance(item),
        }
        # NB: no "overrides" key, ever. See the module docstring.
        definitions.append(entry)

    overlay = {
        "schema_version": 1,
        "set_id": kit,
        "tier": "domain",
        "note": (
            "Domain overlay produced by scripts/scaffold_kit.py from a K1 "
            "intake. Extends the kernel base set; overrides none. An override "
            "must be authored, naming the base address it replaces and why."
        ),
        "definitions": definitions,
    }
    return overlay, needs_author


def check_base_collisions(overlay: Dict[str, Any]) -> Tuple[List[str], bool]:
    """Ids that already exist in the kernel base set.

    Returns (collisions, base_was_available). The second value matters: with
    no base set reachable -- which is the normal case in this repo, where the
    kernel is not vendored -- "no collisions" means "not checked", and saying
    otherwise would be a clean bill of health nobody issued.
    """
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from app.core.formula_definitions import load_definitions
    except Exception:
        return [], False

    base = load_definitions()
    if not base:
        return [], False
    base_ids = {entry["id"] for entry in base}
    return sorted(
        d["id"] for d in overlay["definitions"] if d["id"] in base_ids
    ), True


# -- the other sections ----------------------------------------------------


def build_source_manifest(kit: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    families: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for item in items:
        key = (item.get("source", ""), item.get("source_ref", ""))
        record = families.setdefault(
            key,
            {
                "source_id": f"{slugify(key[0])}_{slugify(key[1])}"[:60],
                "source_class": key[0],
                "reference": key[1],
                "contributor_id": item.get("contributor_id", ""),
                "sections": [],
                "item_count": 0,
            },
        )
        record["item_count"] += 1
        if item.get("section") not in record["sections"]:
            record["sections"].append(item.get("section"))
    return {
        "schema_version": "1.0.0",
        "pack_id": f"{kit}_intake_v1",
        "domain": kit,
        "note": (
            "Derived from the K1 intake. Every record is a (source, reference) "
            "pair a contributor stated; nothing here was inferred."
        ),
        "source_families": sorted(families.values(), key=lambda r: r["source_id"]),
    }


def render_prompt(kit: str, vocabulary, refusal_traps) -> str:
    lines = [
        f"You are the {kit.replace('_', ' ')} domain assistant.",
        "",
        "Answer from retrieved evidence and the definitions supplied to you.",
        "Say when evidence is insufficient rather than inventing an answer.",
        "",
    ]
    if vocabulary:
        lines.append("DOMAIN VOCABULARY (from the encoding sheet):")
        for item in vocabulary:
            lines.append(f"  - {item['text']}   [{item['source']}: {item['source_ref']}]")
        lines.append("")
    if refusal_traps:
        lines.append("REFUSE THESE. Each is a failure the domain expert named:")
        for item in refusal_traps:
            lines.append(f"  - {item['text']}   [{item['source']}: {item['source_ref']}]")
        lines.append("")
    lines.append(
        "This prompt was assembled by scripts/scaffold_kit.py from a sourced "
        "intake. Every line above is traceable to a sheet entry."
    )
    return "\n".join(lines) + "\n"


def build_entity_schema(item: Dict[str, Any], kit: str) -> Tuple[str, Dict[str, Any]]:
    ident = slugify(item["text"])[:60] or "entity"
    return ident, {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"{pascal(kit)}{pascal(ident)}",
        "type": "object",
        "description": item["text"],
        "x-provenance": _provenance(item),
        # No properties are invented. The author fills these in at K4; an
        # empty schema is honestly empty, a guessed one is quietly wrong.
        "properties": {},
    }


# -- scaffolding -----------------------------------------------------------


def substitute(text: str, values: Dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{%s}}" % key, value)
    return text


def copy_template(kit_dir: Path, values: Dict[str, str]) -> List[str]:
    """Copy _template, substituting placeholders in names and text content."""
    written: List[str] = []
    for source in sorted(TEMPLATE_DIR.rglob("*")):
        if source.is_dir() or "__pycache__" in source.parts:
            continue
        relative = substitute(str(source.relative_to(TEMPLATE_DIR)), values)
        target = kit_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text(
                substitute(source.read_text(encoding="utf-8"), values),
                encoding="utf-8",
                newline="\n",
            )
        except UnicodeDecodeError:
            shutil.copy2(source, target)
        written.append(relative)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold a kit directory from a K1 intake (stage K3)."
    )
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--force", action="store_true", help="Overwrite an existing kit")
    parser.add_argument("--out", type=Path, default=None, help="Kit directory override")
    args = parser.parse_args()

    if not args.intake.is_file():
        print(f"No such intake: {args.intake}", file=sys.stderr)
        return 2

    intake = load_intake(args.intake)
    kit = intake.get("kit")
    if not kit:
        print("Intake declares no kit id.", file=sys.stderr)
        return 2

    sections = intake.get("sections") or {}
    all_items = [item for entries in sections.values() for item in entries]
    if not all_items:
        print(
            f"Intake for {kit!r} encoded nothing. Nothing to scaffold -- fix the "
            f"sheet's sources and re-run intake_kit.py.",
            file=sys.stderr,
        )
        return 2

    kit_dir = args.out or (KITS_DIR / kit)
    if kit_dir.exists() and not args.force:
        print(
            f"{kit_dir} already exists. Re-run with --force to overwrite, but "
            f"read what is there first: a scaffold overwrites author edits.",
            file=sys.stderr,
        )
        return 2

    values = {
        "domain": kit,
        "Domain": pascal(kit),
        "name": intake.get("name") or f"{pascal(kit)} Suite",
        "description": (
            f"{pascal(kit)} domain kit scaffolded from a sourced encoding "
            f"sheet ({intake.get('intake', {}).get('sheet', 'unknown')})."
        ),
        "status": SCAFFOLD_STATUS,
        "tags_json": json.dumps(["domain", "container", kit, "scaffolded"]),
    }
    copy_template(kit_dir, values)

    manifest_path = kit_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["trust_tier"] = SCAFFOLD_TRUST_TIER
    manifest["_trust_tier_note"] = (
        "No reviewer has seen this kit's content. The Factory compliance gate "
        "refuses to build with an unvouched block; a reviewer raises this to "
        "contributor_reviewed at K4."
    )
    manifest["_intake"] = {
        "sheet": intake.get("intake", {}).get("sheet"),
        "sheet_sha256": intake.get("intake", {}).get("sheet_sha256"),
        "contributor_id": intake.get("intake", {}).get("contributor_id"),
    }
    data_dir = kit_dir / "app" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    overlay, needs_author = build_definitions(kit, sections.get("formulas") or [])
    (data_dir / "domain_definitions.json").write_text(
        json.dumps(overlay, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    manifest["data"] = ["app/data/domain_definitions.json"]

    (kit_dir / "source_manifest.json").write_text(
        json.dumps(build_source_manifest(kit, all_items), indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    schemas_dir = kit_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    for entity in sections.get("entities") or []:
        name, schema = build_entity_schema(entity, kit)
        (schemas_dir / f"{name}.json").write_text(
            json.dumps(schema, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    prompt_path = kit_dir / "prompts" / f"{kit}_expert.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(
        render_prompt(
            kit, sections.get("vocabulary") or [], sections.get("refusal_traps") or []
        ),
        encoding="utf-8",
        newline="\n",
    )

    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    collisions, base_checked = check_base_collisions(overlay)

    print(f"Scaffolded {kit!r} -> {kit_dir}")
    print(f"  status: {SCAFFOLD_STATUS} (not installable until authored)")
    print(f"  trust_tier: {SCAFFOLD_TRUST_TIER} (the Factory gate will refuse it)")
    print(f"  definitions: {len(overlay['definitions'])}")
    for section in ("entities", "workflows", "vocabulary", "refusal_traps", "precedence"):
        count = len(sections.get(section) or [])
        if count:
            print(f"  {section}: {count}")

    if collisions:
        print(f"  COLLIDES with base definitions: {', '.join(collisions)}")
        print(
            "    The precedence contract refuses an undeclared shadow. Author "
            "an override naming the base address and the reason, or rename."
        )
    elif not base_checked:
        print(
            "  base-set collisions NOT CHECKED (the kernel set is not reachable "
            "from this repo) -- this is not a clean bill of health"
        )

    if needs_author:
        print(f"  NEEDS THE AUTHOR: {len(needs_author)}")
        for note in needs_author[:10]:
            print(f"    {note}")

    return 1 if (needs_author or collisions) else 0


if __name__ == "__main__":
    raise SystemExit(main())
