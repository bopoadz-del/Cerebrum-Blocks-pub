#!/usr/bin/env python3
"""Store-wide conformance report. REPORT-ONLY: this never fails a build.

KERNEL_DEFAULTS 1.4 and 1.6, plus K2 / K3. Five checks over every
block in ``BLOCK_REGISTRY``:

``constructor``
    Liskov. Can the block be constructed the way the base class promises --
    ``Block(hal_block=..., config=...)``? #88 is this check: ``DatabaseBlock``
    narrowed its constructor, so no pipeline could build it, and nothing
    noticed until a zip failed to boot.

``smoke``
    Instantiate and invoke through one harness with the block's declared
    minimal input, and record the resulting ``BlockResult`` status. #87 is
    this check: ``CacheManager``'s local fallback was unreachable, and a
    store-wide invoke would have said so.

``three_tests``
    Does the block have a test file, and does it carry the happy path, the
    planted failure and the mutation probe? (KERNEL_DEFAULTS 1.3.)

``source_class_render``
    KERNEL_DEFAULTS K2. For a RAG-derived block (tags include ``rag``,
    or the module uses the answer contract): does every citation path
    emit ``source_class`` and does the answer layer render it?
    Non-RAG blocks are skipped. REPORT-ONLY.

``coverage_honesty``
    KERNEL_DEFAULTS K3. For a RAG-derived block: is the ``N of M
    indexed`` line present, and is a ``does-not-exist`` claim refused
    below 100% coverage? Non-RAG blocks are skipped. REPORT-ONLY.

``brief_scope``
    L2.2. Does ``block.json`` carry valid ``reads`` / ``writes`` /
    ``never`` / ``acceptance``? Missing or invalid fields are reported.
    Empty lists are valid (measured nothing / could not measure).
    REPORT-ONLY -- ``BRIEF_SCOPE_FAIL_CLOSED`` is False until the
    owner-gated flip. This check walks ``block_registry/``, not just
    ``BLOCK_REGISTRY``, because Factory inventory is a store query.

WHY THIS EXITS 0 NO MATTER WHAT
-------------------------------
Cowork is booting generated zips from this store right now, and these checks
measure code written long before the contract existed. Turning them red today
would block the critical path to report a backlog everybody already knows
about. So the exit code is always 0 and the output is a table.

The flip to enforcing is a SEPARATE PR, after P7 is DONE, with the owner's
tick. Until then: this is reporting, not a gate. Do not describe it as one.

A NOTE ON INVOKING EVERY BLOCK
------------------------------
The smoke check really does call ``process()`` on every block. Blocks that
reach for a network, a database or a key will fail -- that is the point, and
in CI there are no credentials for them to use. Each call is bounded by
``--timeout`` so a block that hangs cannot hang the report.

Usage:
    python scripts/lane2_conformance.py                 # full report
    python scripts/lane2_conformance.py --no-invoke     # skip the smoke
    python scripts/lane2_conformance.py --summary-only
    python scripts/lane2_conformance.py --baseline <baseline.md>
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Extended blocks are only registered in the legacy (non-virgin) boot. The
# report is about the whole store, so ask for all of them.
os.environ.setdefault("CEREBRUM_VIRGIN", "false")
os.environ.setdefault("ENV", "test")

REGISTRY_ROOT = ROOT / "block_registry"
TESTS_ROOT = ROOT / "tests"

PASS = "pass"
FAIL = "fail"
SKIP = "skip"

CHECKS = (
    "constructor",
    "smoke",
    "three_tests",
    "source_class_render",
    "coverage_honesty",
    "brief_scope",
)

#: A block is RAG-derived when its tags say so. There is no ``rag_core``
#: base class in this store (evidence-blocked at ddda63f); inventing one
#: so this check had a parent would be a parallel architecture.
RAG_TAG = "rag"

#: Markers the three mandatory tests leave behind. Matched case-insensitively
#: against a block's test file. Kept loose on purpose: the point is to find
#: tests that exist and are missing a category, not to police wording.
_CATEGORY_PATTERNS = {
    "happy": re.compile(r"happy[_ ]path", re.I),
    "planted_failure": re.compile(r"planted[_ ]failure|_broken|raises|swallow", re.I),
    "mutation_probe": re.compile(r"mutation[_ ]probe|removing[_ ]the|degrade", re.I),
}


# -- results ---------------------------------------------------------------


class Row:
    __slots__ = ("block", "check", "status", "note")

    def __init__(self, block: str, check: str, status: str, note: str = "") -> None:
        self.block = block
        self.check = check
        self.status = status
        self.note = note

    def as_dict(self) -> Dict[str, str]:
        return {
            "block": self.block,
            "check": self.check,
            "status": self.status,
            "note": self.note,
        }


# -- check (a): Liskov constructor conformance -----------------------------


def check_constructor(cls: Any) -> Row:
    """Can this class be built the way the base class promises?

    Checked by binding the signature rather than constructing, so a block
    with an expensive or side-effecting ``__init__`` is not run twice. The
    smoke check constructs it for real straight after.
    """
    name = getattr(cls, "name", None) or cls.__name__
    try:
        signature = inspect.signature(cls)
    except (TypeError, ValueError) as exc:
        return Row(name, "constructor", FAIL, "signature unavailable: %s" % exc)

    for kwargs in ({}, {"hal_block": None, "config": {}}):
        try:
            signature.bind(**kwargs)
        except TypeError as exc:
            return Row(
                name,
                "constructor",
                FAIL,
                "does not accept %s -- %s"
                % (("()" if not kwargs else "(hal_block=..., config=...)"), exc),
            )
    return Row(name, "constructor", PASS)


# -- check (b): store-wide smoke ------------------------------------------


def _manifest_for(block_name: str) -> Optional[Dict[str, Any]]:
    path = REGISTRY_ROOT / block_name / "block.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


_PLACEHOLDER = {
    "string": "",
    "text": "",
    "json": {},
    "object": {},
    "number": 0,
    "percentage": 0,
    "boolean": False,
    "array": [],
    "list": [],
    "file": "",
    "code": "",
    "markdown": "",
    "any": None,
}


def minimal_input(block_name: str) -> Dict[str, Any]:
    """The block's DECLARED minimal input, and nothing invented.

    Read from ``requires_inputs`` when the manifest declares it (L2.2), and
    otherwise from the required entries of the legacy ``inputs`` field. Most
    manifests declare neither, so most blocks are invoked with ``{}`` -- which
    is the honest minimum and is exactly what a caller with nothing to give
    would send.
    """
    manifest = _manifest_for(block_name) or {}
    declared = manifest.get("requires_inputs")
    if isinstance(declared, list) and declared:
        payload = {}
        for entry in declared:
            if isinstance(entry, dict) and entry.get("name"):
                payload[entry["name"]] = _PLACEHOLDER.get(entry.get("type"))
        return payload

    payload = {}
    for entry in manifest.get("inputs") or []:
        if isinstance(entry, dict) and entry.get("required") and entry.get("name"):
            payload[entry["name"]] = _PLACEHOLDER.get(entry.get("type"))
    return payload


async def _invoke(cls: Any, block_name: str, timeout: float) -> Row:
    from app.core.contract_block import safe_call

    try:
        block = cls()
    except Exception as exc:
        return Row(
            block_name,
            "smoke",
            FAIL,
            "could not instantiate: %s: %s" % (type(exc).__name__, exc),
        )

    payload = minimal_input(block_name)
    try:
        result = await asyncio.wait_for(safe_call(block, payload), timeout=timeout)
    except asyncio.TimeoutError:
        return Row(block_name, "smoke", FAIL, "did not return within %ss" % timeout)
    except Exception as exc:  # safe_call should not raise; belt and braces
        return Row(
            block_name,
            "smoke",
            FAIL,
            "harness error: %s: %s" % (type(exc).__name__, exc),
        )

    note = "status=%s" % result.status
    if result.reason:
        note += " -- %s" % result.reason.replace("\n", " ")[:160]

    # An honest refusal is the contract working, not a defect. A block that
    # declines an empty input is behaving correctly; one that returns ok on
    # nothing at all is the interesting case, and the note records it either
    # way for a reader to judge.
    status = PASS if result.status in ("ok", "refused", "partial") else FAIL
    return Row(block_name, "smoke", status, note)


# -- check (c): three tests present ---------------------------------------


def _candidate_test_files(block_name: str, cls: Any) -> List[Path]:
    if not TESTS_ROOT.is_dir():
        return []
    exact = [
        TESTS_ROOT / ("test_%s.py" % block_name),
        TESTS_ROOT / "blocks" / ("test_%s.py" % block_name),
        TESTS_ROOT / "core" / ("test_%s.py" % block_name),
    ]
    found = [path for path in exact if path.is_file()]
    if found:
        return found

    # Fall back to any test file that names the class. Deliberately not a
    # substring match on the block name: "auth" would claim every file that
    # mentions authentication and report coverage that is not there.
    class_name = cls.__name__
    hits = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if class_name in text:
            hits.append(path)
    return hits


def _display(path: Path) -> str:
    """Repo-relative when possible, absolute otherwise.

    ``Path.relative_to`` RAISES for a path outside the repo. A report whose
    job is to survive 129 misbehaving blocks must not die formatting one of
    their filenames.
    """
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def check_three_tests(block_name: str, cls: Any) -> Row:
    paths = _candidate_test_files(block_name, cls)
    if not paths:
        return Row(block_name, "three_tests", FAIL, "no test file found")

    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore") for path in paths
    )
    missing = [
        category
        for category, pattern in _CATEGORY_PATTERNS.items()
        if not pattern.search(text)
    ]
    where = ", ".join(_display(path) for path in paths[:2])
    if missing:
        return Row(
            block_name,
            "three_tests",
            FAIL,
            "missing %s (in %s)" % ("+".join(missing), where),
        )
    return Row(block_name, "three_tests", PASS, where)


# -- checks (d) and (e): KERNEL_DEFAULTS K2 / K3 --------------------------


def is_rag_derived(cls: Any) -> bool:
    """True when the block is an answer layer this store treats as RAG.

    Tags are the only honest signal until a ``rag_core`` base exists.
    ``grounded_answer`` lives in the kernel kit, not BLOCK_REGISTRY, and
    is covered by store-enforced tests rather than this table.
    """
    tags = [str(tag).lower() for tag in (getattr(cls, "tags", None) or [])]
    return RAG_TAG in tags


def _module_source(cls: Any) -> str:
    module = inspect.getmodule(cls)
    if module is None or not getattr(module, "__file__", None):
        return ""
    try:
        return Path(module.__file__).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def check_source_class_render(block_name: str, cls: Any) -> Row:
    """K2, report-only: RAG blocks emit and render ``source_class``."""
    if not is_rag_derived(cls):
        return Row(block_name, "source_class_render", SKIP, "not a RAG answer layer")

    text = _module_source(cls)
    uses_contract = "answer_contract" in text
    emits_class = "source_class" in text
    if uses_contract and emits_class:
        return Row(
            block_name,
            "source_class_render",
            PASS,
            "emits source_class via the answer contract",
        )
    missing = []
    if not uses_contract:
        missing.append("answer_contract")
    if not emits_class:
        missing.append("source_class")
    return Row(
        block_name,
        "source_class_render",
        FAIL,
        "RAG answer layer missing %s" % "+".join(missing),
    )


def check_coverage_honesty(block_name: str, cls: Any) -> Row:
    """K3, report-only: RAG blocks carry the coverage line and the ban."""
    if not is_rag_derived(cls):
        return Row(block_name, "coverage_honesty", SKIP, "not a RAG answer layer")

    text = _module_source(cls)
    has_line = "coverage_line" in text or " of " in text and "indexed" in text
    has_ban = "does-not-exist" in text or "does_not_exist" in text
    if has_line and has_ban:
        return Row(
            block_name,
            "coverage_honesty",
            PASS,
            "N of M indexed + does-not-exist prohibition",
        )
    missing = []
    if not has_line:
        missing.append("coverage_line")
    if not has_ban:
        missing.append("does-not-exist prohibition")
    return Row(
        block_name,
        "coverage_honesty",
        FAIL,
        "RAG answer layer missing %s" % "+".join(missing),
    )


# -- the run ---------------------------------------------------------------


def collect(invoke: bool = True, timeout: float = 20.0) -> List[Row]:
    from app.blocks import BLOCK_REGISTRY

    rows: List[Row] = []
    for block_name in sorted(BLOCK_REGISTRY.keys()):
        try:
            cls = BLOCK_REGISTRY[block_name]
        except Exception as exc:
            for check in CHECKS:
                if check == "brief_scope":
                    # Disk-manifest check; collected separately below.
                    continue
                rows.append(
                    Row(
                        block_name,
                        check,
                        FAIL,
                        "import failed: %s: %s" % (type(exc).__name__, exc),
                    )
                )
            continue

        rows.append(check_constructor(cls))
        if invoke:
            rows.append(asyncio.run(_invoke(cls, block_name, timeout)))
        else:
            rows.append(Row(block_name, "smoke", SKIP, "--no-invoke"))
        rows.append(check_three_tests(block_name, cls))
        rows.append(check_source_class_render(block_name, cls))
        rows.append(check_coverage_honesty(block_name, cls))

    rows.extend(collect_brief_scope())
    return rows


# -- check (f): L2.2 brief-scope fields (report-only until the flip) ------


def check_brief_scope(block_name: str) -> Row:
    """Report missing or invalid ``reads``/``writes``/``never``/``acceptance``.

    Never fail-closes the store. Empty lists pass. Missing keys and
    malformed entries fail the *row* so the table shows the backlog;
    ``main()`` still exits 0. Flip gate: ``BRIEF_SCOPE_FAIL_CLOSED``.
    """
    from app.core.manifest_contract import (
        BRIEF_SCOPE_KEYS,
        check_brief_scope_fields,
        missing_brief_scope_fields,
    )

    manifest = _manifest_for(block_name)
    if manifest is None:
        return Row(
            block_name,
            "brief_scope",
            FAIL,
            "no block.json on disk -- Factory cannot query this id",
        )

    invalid = check_brief_scope_fields(manifest)
    missing = missing_brief_scope_fields(manifest)
    if invalid:
        return Row(
            block_name,
            "brief_scope",
            FAIL,
            "invalid: %s" % "; ".join(invalid)[:200],
        )
    if missing:
        return Row(
            block_name,
            "brief_scope",
            FAIL,
            "missing %s (report-only until flip)" % "+".join(missing),
        )

    declared = []
    for field in BRIEF_SCOPE_KEYS:
        value = manifest.get(field)
        if isinstance(value, list) and value:
            declared.append("%s=%d" % (field, len(value)))
        else:
            declared.append("%s=empty" % field)
    return Row(block_name, "brief_scope", PASS, ", ".join(declared))


def collect_brief_scope() -> List[Row]:
    """Every on-disk registry entry, including ids not in BLOCK_REGISTRY."""
    if not REGISTRY_ROOT.is_dir():
        return []
    rows: List[Row] = []
    for path in sorted(REGISTRY_ROOT.iterdir()):
        if not path.is_dir() or path.name.startswith("__"):
            continue
        if not (path / "block.json").is_file():
            continue
        rows.append(check_brief_scope(path.name))
    return rows


def counts(rows: List[Row]) -> Dict[str, Dict[str, int]]:
    tally: Dict[str, Dict[str, int]] = {
        check: {PASS: 0, FAIL: 0, SKIP: 0} for check in CHECKS
    }
    for row in rows:
        tally.setdefault(row.check, {PASS: 0, FAIL: 0, SKIP: 0})
        tally[row.check][row.status] = tally[row.check].get(row.status, 0) + 1
    return tally


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render(rows: List[Row], summary_only: bool = False) -> str:
    tally = counts(rows)
    blocks = sorted({row.block for row in rows})
    unimportable = sorted(
        {row.block for row in rows if row.note.startswith("import failed:")}
    )
    lines = [
        "## Lane 2 — store-wide conformance (REPORT-ONLY)",
        "",
        "This table never fails the build. It measures code written before the "
        "contract existed; the enforcement flip is a separate PR after P7, "
        "with the owner's tick.",
        "",
        "%d blocks checked." % len(blocks),
        "",
    ]
    if unimportable:
        lines += [
            "> **%d block(s) could not be imported in this environment** and are "
            "counted as failures on every check: %s."
            % (len(unimportable), ", ".join("`%s`" % b for b in unimportable)),
            ">",
            "> On a machine missing a block's dependency this says nothing about "
            "the block. In CI, where every dependency is installed, an import "
            "failure is a real defect. Read the numbers from the CI run, not a "
            "local one.",
            "",
        ]
    lines += [
        "| check | pass | fail | skip |",
        "| --- | ---: | ---: | ---: |",
    ]
    for check in CHECKS:
        row = tally.get(check, {})
        lines.append(
            "| `%s` | %d | %d | %d |"
            % (check, row.get(PASS, 0), row.get(FAIL, 0), row.get(SKIP, 0))
        )
    lines.append("")

    if summary_only:
        return "\n".join(lines)

    failures = [row for row in rows if row.status == FAIL]
    passes = [row for row in rows if row.status != FAIL]

    lines += [
        "### Non-conformers (%d)" % len(failures),
        "",
        "| block | check | result | note |",
        "| --- | --- | --- | --- |",
    ]
    if failures:
        for row in sorted(failures, key=lambda r: (r.check, r.block)):
            lines.append(
                "| `%s` | %s | %s | %s |"
                % (row.block, row.check, row.status, _escape(row.note))
            )
    else:
        lines.append("| — | — | — | nothing outstanding |")

    lines += [
        "",
        "<details><summary>Conforming (%d)</summary>" % len(passes),
        "",
        "| block | check | result | note |",
        "| --- | --- | --- | --- |",
    ]
    for row in sorted(passes, key=lambda r: (r.check, r.block)):
        lines.append(
            "| `%s` | %s | %s | %s |"
            % (row.block, row.check, row.status, _escape(row.note))
        )
    lines += ["", "</details>", ""]
    return "\n".join(lines)


def render_baseline(rows: List[Row]) -> str:
    tally = counts(rows)
    blocks = sorted({row.block for row in rows})
    lines = [
        "# Lane 2 conformance baseline",
        "",
        "Generated by `scripts/lane2_conformance.py`. This is the count of "
        "non-conformers at the moment the report-only checks landed -- the "
        "number the enforcement flip will have to get to zero.",
        "",
        "Blocks checked: **%d**" % len(blocks),
        "",
        "Generated in CI, where every dependency is installed. A local run on "
        "a machine missing a block's dependency reports import failures that "
        "are not defects.",
        "",
        "| check | pass | fail | skip |",
        "| --- | ---: | ---: | ---: |",
    ]
    for check in CHECKS:
        row = tally.get(check, {})
        lines.append(
            "| `%s` | %d | %d | %d |"
            % (check, row.get(PASS, 0), row.get(FAIL, 0), row.get(SKIP, 0))
        )
    lines += ["", "## Non-conformers", ""]
    failures = [row for row in rows if row.status == FAIL]
    if not failures:
        lines.append("None.")
    for check in CHECKS:
        subset = [row for row in failures if row.check == check]
        lines += ["### `%s` (%d)" % (check, len(subset)), ""]
        if not subset:
            lines += ["None.", ""]
            continue
        for row in sorted(subset, key=lambda r: r.block):
            lines.append("- `%s` — %s" % (row.block, row.note or "no note"))
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-invoke", action="store_true", help="skip the smoke check")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--json", type=Path, help="write raw rows here")
    parser.add_argument("--baseline", type=Path, help="write the baseline doc here")
    args = parser.parse_args()

    rows = collect(invoke=not args.no_invoke, timeout=args.timeout)
    report = render(rows, summary_only=args.summary_only)
    print(report)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps([row.as_dict() for row in rows], indent=2) + "\n",
            encoding="utf-8",
        )
    if args.baseline:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(render_baseline(rows) + "\n", encoding="utf-8")

    # ALWAYS 0. See the module docstring: this phase reports, it does not gate.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
