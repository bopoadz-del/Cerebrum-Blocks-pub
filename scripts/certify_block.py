#!/usr/bin/env python3
"""Block certification — the three bars, automated.

Bars (from the Construction Capability Audit, The_Fork):

  1. **Not a stub** — the entry method has a real body.
  2. **Current** — the advertised id resolves to exactly one importable
     implementation with identity metadata (registry census keys).
  3. **Really tested** — control-delete: the entry method is gutted to a
     plausible success (``{"block": <name>, "status": "success"}``) and the
     block's tests MUST go RED. A suite that stays green on a plausible
     success proves nothing about the block's payloads.

Baseline (tests GREEN) is required before the mutation run. The mutation is
applied to the working file and restored via ``git checkout``; the script
refuses to run on a dirty file.

Usage:
  python scripts/certify_block.py --block chat
  python scripts/certify_block.py --all        # CI: every certified entry
  python scripts/certify_block.py --list

Certifications live in ``block_certifications.json`` (this repo's root).
New certifications must name a real fixture: the tests must exercise a real
input artifact (file, image, schedule) — the single best predictor that a
control-delete would have been caught by a human, per the audit.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
REGISTRY_PATH = REPO_ROOT / "block_certifications.json"

GUT_RETURN = ast.Return(
    value=ast.Call(
        func=ast.Name(id="dict", ctx=ast.Load()),
        args=[],
        keywords=[
            ast.keyword(arg="block", value=ast.Name(id="self", ctx=ast.Load())),
            ast.keyword(arg="status", value=ast.Constant(value="success")),
        ],
    )
)


def load_certifications() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def find_entry(block_id: str) -> dict | None:
    for entry in load_certifications()["blocks"]:
        if entry["block"] == block_id:
            return entry
    return None


def _resolve_entry(entry: dict):
    """Import the class and locate the file where its entry method is defined.

    The method may be inherited from a base class; the control-delete must
    mutate the defining file, and bar 1 must judge that definition.
    """
    module = __import__(entry["module"], fromlist=[entry["class"]])
    cls = getattr(module, entry["class"])
    method = getattr(cls, entry.get("method", "execute"))
    src_file = Path(inspect.getfile(cls))
    return cls, method, src_file


def _entry_body_is_hollow(method_source: str) -> bool:
    tree = ast.parse(textwrap.dedent(method_source))
    node = tree.body[0] if tree.body else None
    if node is None or not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return True
    body = [
        stmt
        for stmt in node.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    if not body:
        return True
    if len(body) == 1:
        only = body[0]
        if isinstance(only, ast.Pass):
            return True
        if isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant) and only.value.value is Ellipsis:
            return True
        if isinstance(only, ast.Raise) and isinstance(getattr(only, "exc", None), ast.Call):
            func = only.exc.func
            if isinstance(func, ast.Name) and func.id == "NotImplementedError":
                return True
        if isinstance(only, ast.Return) and only.value is None:
            return True
    return False


def _gutter(class_name: str, method: str, source: str) -> str:
    """Return source with the entry method's body replaced by a plausible success."""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == method:
                    member.body = [GUT_RETURN]
                    break
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def _run_pytest(test_paths: list[str]) -> subprocess.CompletedProcess:
    # -rs: a skipped file is not a passing file. Without the skip summary a
    # block certified "tests green" can be one whose entire suite sat behind
    # an importorskip for an undeclared dependency.
    return subprocess.run(
        [sys.executable, "-m", "pytest", *test_paths, "-q", "-rs"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )


PYTEST_TAIL_LINES = 25


def _pytest_tail(proc: subprocess.CompletedProcess) -> list[str]:
    """The last lines of a failed pytest run, indented for the findings list."""
    captured = f"{proc.stdout or ''}{proc.stderr or ''}".strip()
    if not captured:
        return ["  (pytest produced no output)"]
    tail = captured.splitlines()[-PYTEST_TAIL_LINES:]
    return ["  pytest output (tail):", *(f"  | {line}" for line in tail)]


def _git_clean(path: Path) -> bool:
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--", str(path.relative_to(REPO_ROOT))],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.stdout.strip() == ""


def certify(entry: dict) -> tuple[bool, list[str]]:
    block_id = entry["block"]
    findings: list[str] = []
    notes: list[str] = []
    test_paths = entry.get("tests", [])
    method_name = entry.get("method", "execute")

    try:
        cls, method_obj, _imp_path = _resolve_entry(entry)
    except Exception as exc:  # noqa: BLE001
        return False, [f"BAR2 FAIL: cannot resolve entry: {exc}"]

    # The control-delete mutates the file where the method is DEFINED
    # (it may be inherited from a shared base, e.g. TypedBlock.execute).
    imp_path = Path(method_obj.__code__.co_filename)
    if not imp_path.is_file():
        return False, [f"BAR2 FAIL: defining file missing: {imp_path}"]

    # Bar 1 — not a stub (judged on the defining source).
    try:
        method_source = inspect.getsource(method_obj)
    except (OSError, TypeError):
        findings.append(f"BAR1 FAIL: no source for {cls.__name__}.{method_name}")
    else:
        if _entry_body_is_hollow(method_source):
            findings.append(f"BAR1 FAIL: {cls.__name__}.{method_name} is hollow")

    identity = REPO_ROOT / "block_registry" / block_id / "block.json"
    if not identity.is_file():
        findings.append(f"BAR2 FAIL: block_registry/{block_id}/block.json missing")
    else:
        try:
            data = json.loads(identity.read_text(encoding="utf-8"))
        except ValueError as exc:
            findings.append(f"BAR2 FAIL: block.json unreadable: {exc}")
        else:
            for key in ("id", "name", "version"):
                if not data.get(key):
                    findings.append(f"BAR2 FAIL: block.json missing identity key {key!r}")

    # Bar 3 — control-delete. Baseline GREEN required; mutation must go RED.
    baseline = _run_pytest(test_paths)
    if baseline.returncode != 0:
        # Name the failure. "exit 1" on its own sent a reviewer to reproduce
        # the whole run locally to learn WHICH assertion broke; the pytest
        # tail was captured and thrown away. A gate that reports a number
        # instead of a reason is a gate nobody can act on from the log.
        findings.append(f"BAR3 FAIL: baseline tests not green (exit {baseline.returncode})")
        findings.extend(_pytest_tail(baseline))
        return False, findings

    if not _git_clean(imp_path):
        findings.append("BAR3 FAIL: implementation file is dirty; refusing to mutate")
        return False, findings

    source = imp_path.read_text(encoding="utf-8")
    qualname_parts = method_obj.__qualname__.split(".")
    defining_class = (
        qualname_parts[-2] if len(qualname_parts) >= 2 else cls.__name__
    )
    tree = ast.parse(source)
    has_class = any(
        isinstance(node, ast.ClassDef) and node.name == defining_class
        for node in tree.body
    )
    if not has_class:
        findings.append(
            f"BAR3 FAIL: class {defining_class!r} not found in "
            f"{imp_path.relative_to(REPO_ROOT)} to mutate"
        )
        return False, findings
    if defining_class != cls.__name__:
        notes.append(
            f"NOTE: {cls.__name__}.{method_name} is inherited from "
            f"{defining_class}; the control-delete mutates the shared base"
        )
    gutted = _gutter(defining_class, method_name, source)
    try:
        imp_path.write_text(gutted, encoding="utf-8")
        mutated = _run_pytest(test_paths)
    finally:
        subprocess.run(
            ["git", "checkout", "--", str(imp_path.relative_to(REPO_ROOT))],
            cwd=str(REPO_ROOT),
            capture_output=True,
            timeout=60,
        )
    if mutated.returncode == 0:
        findings.append(
            "BAR3 FAIL: suite stayed GREEN on a plausible-success gut "
            f"(tests prove nothing about {cls.__name__}.{method_name} payloads)"
        )
    return (not findings), notes + findings


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--block", help="certify one block by id")
    group.add_argument("--all", action="store_true", help="certify every CI-included entry")
    group.add_argument("--list", action="store_true", help="list certification entries")
    args = parser.parse_args()

    data = load_certifications()
    if args.list:
        for entry in data["blocks"]:
            flag = "CI" if entry.get("include_in_ci") else "manual"
            print(f"{entry['block']:<28} certified={entry.get('certified')} [{flag}] fixture={entry.get('fixture')}")
        return 0

    entries = (
        [e for e in data["blocks"] if e.get("include_in_ci") and e.get("certified")]
        if args.all
        else [find_entry(args.block)]
    )
    if not entries or any(e is None for e in entries):
        print("no such certification entry")
        return 2

    failed = False
    for entry in entries:
        ok, findings = certify(entry)
        status = "PASS" if ok else "FAIL"
        print(f"{status}  {entry['block']}")
        for f in findings:
            print(f"      {f}")
        failed = failed or not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
