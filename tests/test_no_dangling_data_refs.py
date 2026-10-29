"""ST-7 gate: app code must not read a data file the tree does not ship.

Two scans over app/ and block_registry/ source:

* module-relative paths built from ``Path(__file__)`` (``.parent`` /
  ``.parents[n]`` / ``.resolve()``) joined with string literals by ``/``;
* repo-relative string literals (``"data/CEREBRUM_SKILL.md"``) whose first
  segment is a top-level directory of this repository.

Every resolved path ending .json/.jsonl/.yaml/.yml/.md/.csv must exist in
the tree or sit under a RUNTIME_GENERATED prefix (written at runtime, never
source). A second test asserts no .gitignore rule ignores a path the code
reads (the bare ``data/`` rule dropped app/data/procedures/procedures_db.json).
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("app", "block_registry")
SUFFIXES = (".json", ".jsonl", ".yaml", ".yml", ".md", ".csv")
# Written at runtime under DATA_DIR (default ./data); never source.
RUNTIME_GENERATED = ("data/storage/", "data/vector/", "data/captures/", "data/uploads/")


def _file_path_expr(node: ast.AST, here: Path) -> Optional[Path]:
    """Resolve Path(__file__)[.parent|.parents[n]|.resolve()]* / "lit" ... or None."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _file_path_expr(node.left, here)
        if left is not None and isinstance(node.right, ast.Constant) and isinstance(node.right.value, str):
            return left / node.right.value
        return None
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name) and f.id == "Path" and len(node.args) == 1:
            a = node.args[0]
            if isinstance(a, ast.Name) and a.id == "__file__":
                return here
        if isinstance(f, ast.Attribute) and f.attr == "resolve" and not node.args:
            return _file_path_expr(f.value, here)
        return None
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        base = _file_path_expr(node.value, here)
        return base.parent if base is not None else None
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
        base = _file_path_expr(node.value.value, here)
        idx = node.slice
        if base is not None and isinstance(idx, ast.Constant) and isinstance(idx.value, int):
            return base.parents[idx.value]
    return None


def _top_dirs(root: Path) -> set:
    return {p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")}


def iter_data_refs(root: Path, scan_dirs=SCAN_DIRS) -> Iterator[Tuple[str, int, str]]:
    """Yield (source_file, line, repo-relative referenced path)."""
    tops = _top_dirs(root)
    for d in scan_dirs:
        for py in sorted((root / d).rglob("*.py")):
            if "/tests/" in py.as_posix():
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            here = py.resolve()
            for node in ast.walk(tree):
                target: Optional[str] = None
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                    p = _file_path_expr(node, here)
                    if p is not None and p.suffix in SUFFIXES:
                        try:
                            target = p.relative_to(root.resolve()).as_posix()
                        except ValueError:
                            continue
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    s = node.value.removeprefix("./")
                    if (
                        s.endswith(SUFFIXES)
                        and "/" in s
                        and " " not in s
                        and "{" not in s
                        and "*" not in s
                        and s.split("/", 1)[0] in tops
                    ):
                        target = s
                if target is not None:
                    yield py.relative_to(root).as_posix(), node.lineno, target


def dangling(root: Path, scan_dirs=SCAN_DIRS) -> List[str]:
    out = []
    for src, line, ref in iter_data_refs(root, scan_dirs):
        if ref.startswith(RUNTIME_GENERATED):
            continue
        if not (root / ref).exists():
            out.append(f"{src}:{line} -> {ref}")
    return sorted(set(out))


def test_every_literal_data_path_the_code_reads_exists():
    assert dangling(ROOT) == []


def test_scan_finds_the_known_readers():
    refs = {r for _, _, r in iter_data_refs(ROOT)}
    assert "app/data/procedures/procedures_db.json" in refs
    assert "data/CEREBRUM_SKILL.md" in refs


def _mini_repo(tmp_path: Path, ref: str, create: bool) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "reader.py").write_text(
        "from pathlib import Path\n"
        f"P = Path(__file__).parent.parent / {ref.split('/')[0]!r} / {ref.split('/', 1)[1]!r}\n"
        f"Q = open({ref!r})\n"
    )
    if create:
        (tmp_path / ref).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / ref).write_text("{}")
    else:
        (tmp_path / ref.split("/")[0]).mkdir(exist_ok=True)
    return tmp_path


@pytest.mark.parametrize("ref", ["kb/one.json", "rules/two.yaml"])
def test_existing_path_passes(tmp_path, ref):
    root = _mini_repo(tmp_path, ref, create=True)
    assert [r for _, _, r in iter_data_refs(root, ("app",))] == [ref, ref]
    assert dangling(root, ("app",)) == []


@pytest.mark.parametrize("ref", ["kb/fabricated_one.json", "rules/fabricated_two.yaml"])
def test_fabricated_path_fails(tmp_path, ref):
    root = _mini_repo(tmp_path, ref, create=False)
    assert dangling(root, ("app",)) == [f"app/reader.py:2 -> {ref}", f"app/reader.py:3 -> {ref}"]


def test_runtime_generated_prefix_is_not_required_to_exist(tmp_path):
    root = _mini_repo(tmp_path, "data/storage/blob.json", create=False)
    assert dangling(root, ("app",)) == []


def ignored_reads(root: Path, refs: List[str]) -> List[str]:
    """Paths in ``refs`` that a .gitignore rule under ``root`` would ignore."""
    res = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        cwd=root, input="\n".join(refs), capture_output=True, text=True,
    )
    assert res.returncode in (0, 1), res.stderr
    return sorted(res.stdout.split())


def test_gitignore_ignores_no_path_the_code_reads():
    refs = sorted(
        {r for _, _, r in iter_data_refs(ROOT) if not r.startswith(RUNTIME_GENERATED)}
    )
    assert refs, "scan found nothing — the gate would be vacuous"
    assert ignored_reads(ROOT, refs) == []


@pytest.mark.parametrize(
    "rule, ignored",
    [("data/\n", ["app/data/x.json", "data/y.md"]), ("/data/storage/\n", [])],
)
def test_ignored_reads_two_inputs(tmp_path, rule, ignored):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text(rule)
    assert ignored_reads(tmp_path, ["app/data/x.json", "data/y.md"]) == ignored
