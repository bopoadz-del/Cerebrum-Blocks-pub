"""Grounding for generated calculations: which definition answered, or none.

THE PROBLEM THIS SOLVES
-----------------------
``formula_executor_v2`` asks an LLM to write Python for a task and runs it in
the sandbox. The output is a number and some code. Nothing in that output
distinguishes two very different things:

* ``gross_margin_ratio`` computed from the definition the platform ships --
  ``(revenue - cogs) / revenue``, an identity, checkable, sourced;
* ``gross_margin_ratio`` computed from whatever the model decided it meant
  that morning.

Both render as a number with plausible code beside it. The second is the one
that quietly reports a different figure than the client's accountant, and
today there is no way to tell them apart after the fact.

THE THREE STATES
----------------
Every result is classified, and the classification is a fact about the
inputs rather than a judgement about the answer:

``grounded``
    The task names a quantity the definition set defines. The definition is
    injected into the prompt and reported back with its tier and provenance.

``user_specified``
    The task supplies its own arithmetic (``(a - b) / a``, ``price * 1.05``).
    The caller said what to compute, so there is nothing to ground it
    against and nothing is wrong. Deliberately left free -- per the ruling,
    user-specified arithmetic is not second-guessed.

``model_generated``
    The task names a quantity, no definition matches it, and the model
    derived one anyway. Not an error -- it is frequently the right answer --
    but it is the model's derivation rather than the platform's, and the
    output says so.

Only the third is a flag, and it is visible in the result, not buried in an
audit log. A caller can render it; a reviewer can grep for it.

WHERE THE DEFINITIONS COME FROM
-------------------------------
The base set is kernel-tier (<private-repo> #200/#202): it ships into every
generated product via the kernel copytree, at
``app/cerebrum_product_kernel/formulas/universal_definitions.json``. A domain
kit may overlay it -- extend with new ids, or override a base definition by
naming the address it replaces. The precedence rule lives with the kernel;
this module only consumes the resolved set.

In the Store repo itself the kernel is not vendored, so the base set is
absent and every task classifies as ``user_specified`` or
``model_generated``. That is the honest degradation: no definitions means
nothing is grounded, and the output says nothing is grounded rather than
implying it was checked.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Reported on every result. Part of the block's output contract.
GROUNDED = "grounded"
USER_SPECIFIED = "user_specified"
MODEL_GENERATED = "model_generated"

#: The task never reached grounding -- it was rejected before assessment, or
#: the calculation failed. Distinct from the three real states: reporting
#: model_generated here would claim the model derived something, and reporting
#: nothing at all would let a caller's ``result["grounding"]`` raise KeyError
#: on some paths and not others.
NOT_ASSESSED = "not_assessed"


def not_assessed(reason: str) -> Dict[str, Any]:
    """A grounding record for an answer that does not exist.

    Every result the executor emits carries the same keys, so a caller can
    read ``result["grounding"]["derivation"]`` without first working out which
    exit fired.
    """
    return {
        "derivation": NOT_ASSESSED,
        "definitions": [],
        "definition_set_size": 0,
        "note": reason,
    }

#: Where the kernel drops the base set inside a generated product.
_KERNEL_RELATIVE = Path("app") / "cerebrum_product_kernel" / "formulas" / "universal_definitions.json"

#: Where a kit overlay lands once installed.
_OVERLAY_RELATIVE = Path("app") / "data" / "domain_definitions.json"

#: An expression the caller wrote themselves. Two arithmetic operators, or one
#: operator flanked by identifiers/numbers, is enough to say "they told us the
#: maths". Kept deliberately narrow: a stray hyphen in prose must not count as
#: subtraction and silence the flag.
_ARITHMETIC_RE = re.compile(
    r"(?:[A-Za-z_]\w*|\d+(?:\.\d+)?)\s*[*/+]\s*(?:[A-Za-z_]\w*|\d+(?:\.\d+)?)"
    r"|(?:[A-Za-z_]\w*|\d+(?:\.\d+)?)\s*-\s*(?:[A-Za-z_]\w*|\d+(?:\.\d+)?)\s*[)/]"
)


def _search_roots() -> List[Path]:
    """Candidate product roots, nearest first.

    ``CEREBRUM_PRODUCT_ROOT`` wins when set (tests and embedded runtimes use
    it). Otherwise walk up from this file: inside a generated product the
    kernel sits beside ``app/core/``.
    """
    roots: List[Path] = []
    override = os.getenv("CEREBRUM_PRODUCT_ROOT", "").strip()
    if override:
        roots.append(Path(override))
    here = Path(__file__).resolve()
    roots.extend(here.parents[2:5])
    return roots


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("definition set at %s is unreadable: %s", path, exc)
        return None


def load_definitions() -> List[Dict[str, Any]]:
    """The resolved definition set: base tier plus any installed kit overlay.

    Returns an empty list when the kernel is not vendored -- callers must
    treat "no definitions" as "nothing is grounded", never as "nothing needed
    grounding".
    """
    definitions: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}

    for root in _search_roots():
        base = _load_json(root / _KERNEL_RELATIVE)
        if base:
            for entry in base.get("definitions", []):
                entry = dict(entry)
                entry.setdefault("tier", "base")
                seen[entry["id"]] = len(definitions)
                definitions.append(entry)
            break

    for root in _search_roots():
        overlay = _load_json(root / _OVERLAY_RELATIVE)
        if not overlay:
            continue
        origin = overlay.get("set_id", "domain")
        for entry in overlay.get("definitions", []):
            entry = dict(entry)
            entry["origin"] = origin
            ident = entry.get("id")
            if not ident:
                continue
            if ident in seen:
                # The kernel resolver is the authority on whether this
                # override was declared. Reaching here without one means the
                # overlay was installed unresolved; report the domain answer
                # but keep the base address visible so the swap is not silent.
                entry["tier"] = entry.get("tier") or "domain-override of base"
                entry["supersedes"] = definitions[seen[ident]].get("key")
                definitions[seen[ident]] = entry
            else:
                entry.setdefault("tier", "domain-extension")
                seen[ident] = len(definitions)
                definitions.append(entry)
        break

    return definitions


def _phrases(entry: Dict[str, Any]) -> List[str]:
    """The surface forms a task might use to name this definition."""
    forms = {entry["id"].replace("_", " ").lower()}
    name = (entry.get("name") or "").strip().lower()
    if name:
        forms.add(name)
    return [f for f in forms if len(f) > 3]


def match_definitions(task: str, definitions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Definitions the task names, longest phrase first.

    Substring matching on a normalised task. Crude on purpose: a definition
    is injected only when the caller actually used its name, and a near-miss
    yields no match rather than a confident wrong one.
    """
    haystack = re.sub(r"[^a-z0-9]+", " ", (task or "").lower())
    hits = []
    for entry in definitions:
        for phrase in _phrases(entry):
            if phrase in haystack:
                hits.append((len(phrase), entry))
                break
    hits.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in hits]


def task_supplies_its_own_arithmetic(task: str) -> bool:
    """Did the caller write the expression themselves?

    Used to keep ``model_generated`` off tasks where there was never a
    definition to find -- "compute 10 * 8 * 0.2" is not an ungrounded claim
    about a named business quantity.
    """
    return bool(_ARITHMETIC_RE.search(task or ""))


def definitions_prompt_block(matched: List[Dict[str, Any]]) -> str:
    """The authoritative definitions, rendered for the code-gen prompt."""
    if not matched:
        return ""
    lines = [
        "AUTHORITATIVE DEFINITIONS.",
        "These are the platform's definitions for the quantities this task "
        "names. Use them exactly. Do not substitute a different derivation, "
        "and do not silently rename their inputs.",
        "",
    ]
    for entry in matched:
        lines.append(f"  {entry['id']} ({entry.get('tier', 'base')}):")
        lines.append(f"    {entry.get('expression', '<no expression>')}")
        if entry.get("inputs"):
            lines.append(f"    inputs: {', '.join(entry['inputs'])}")
        if entry.get("guards"):
            lines.append(f"    only valid when: {'; '.join(entry['guards'])}")
        if entry.get("supersedes"):
            lines.append(f"    overrides: {entry['supersedes']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def grounding_report(
    task: str, definitions: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Classify a task and name what grounds it. Never raises.

    The returned dict is attached to the block's result, so its shape is part
    of the output contract: ``derivation`` is always present and is always one
    of the three states.
    """
    definitions = load_definitions() if definitions is None else definitions
    matched = match_definitions(task, definitions)

    if matched:
        return {
            "derivation": GROUNDED,
            "definitions": [
                {
                    "id": entry["id"],
                    "tier": entry.get("tier", "base"),
                    "expression": entry.get("expression", ""),
                    "key": entry.get("key", ""),
                    "supersedes": entry.get("supersedes", ""),
                    "provenance": entry.get("provenance", {}),
                }
                for entry in matched
            ],
            "definition_set_size": len(definitions),
            "note": "computed from the platform's definition(s) named above",
        }

    if task_supplies_its_own_arithmetic(task):
        return {
            "derivation": USER_SPECIFIED,
            "definitions": [],
            "definition_set_size": len(definitions),
            "note": "the task supplied its own expression; nothing to ground it against",
        }

    return {
        "derivation": MODEL_GENERATED,
        "definitions": [],
        "definition_set_size": len(definitions),
        "note": (
            "no platform definition matched this task, and the task did not "
            "supply an expression -- the derivation below is the model's, not "
            "the platform's, and has not been checked against a source"
            if definitions
            else "no definition set is available in this runtime, so nothing "
            "was grounded; this is not a statement that grounding was unnecessary"
        ),
    }
