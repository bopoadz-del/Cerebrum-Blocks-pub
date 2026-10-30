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
from typing import Dict, Iterator, List, Optional, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("app", "block_registry", "block_store/kits")
SUFFIXES = (".json", ".jsonl", ".yaml", ".yml", ".md", ".csv")
# Written at runtime under DATA_DIR (default ./data); never source.
RUNTIME_GENERATED = (
    "data/storage/",
    "data/vector/",
    "data/captures/",
    "data/uploads/",
    "data/installed_container_kits.json",  # container_kit_store.py writes it (install state)
    "data/domain_kit_registry.json",  # domain_kit_registry.py json.dump()s it
    "data/block_certifications.json",  # block_validation.py certification store
)

# OPEN-GAP REGISTER, NOT AN ALLOWLIST. Each entry is one exact path the code
# reads that is absent from the tree today, with the reason it cannot be
# restored in this PR. Entries are never globs; an entry whose file exists (or
# that the scan no longer finds) fails the gate, so the register can only
# shrink as gaps close. It exists so a known hole is stated, not hidden.
OPEN_GAPS: Tuple[Tuple[str, str], ...] = (
    (
        "block_store/kits/private_estate_operations/steward_runtime/packs/steward_hospitality_intents_v1/mini/intents.jsonl",
        "never committed: absent from every commit of the pre-snapshot mirror (691fb177bd80); needs recovery from the owner's source or re-authoring (ST-7 ruling 1)",
    ),
    (
        "block_store/kits/private_estate_operations/steward_runtime/packs/steward_facilities_open_v1/mini/assets.jsonl",
        "never committed: absent from every commit of the pre-snapshot mirror (691fb177bd80); needs recovery from the owner's source or re-authoring (ST-7 ruling 1)",
    ),
    (
        "block_store/kits/private_estate_operations/steward_runtime/packs/steward_fleet_open_v1/mini/vehicles.jsonl",
        "never committed: absent from every commit of the pre-snapshot mirror (691fb177bd80); needs recovery from the owner's source or re-authoring (ST-7 ruling 1)",
    ),
    (
        "data/publishers.json",
        "platform publisher registry: held for ST-4 key rotation under the key-gap ruling; not shipped in ST-7",
    ),
    (
        "block_store/data/demo/estate_fixtures.json",
        "estate_kit_router._fixtures reads it (404 when absent); never authored in this repo or the mirror",
    ),
    (
        "block_store/docs/rag/dual_rag.json",
        "reader: block_store/kits/private_estate_operations/estate_kit_router.py::_dual_rag_meta, Path(__file__).parents[2]/docs/rag/dual_rag.json (is_file-guarded); the file lives at block_store/kits/private_estate_operations/surface/dual_rag.json, so the reader path is wrong; code fix is out of ST-7 scope",
    ),
)
GLOB_CHARS = set("*?[]")


Env = Dict[str, List]  # name -> list of Path (roots) or list of str (constants)


def _resolve(node: ast.AST, here: Path, roots: Env, consts: Env) -> Optional[List[Path]]:
    """Resolve a path expression rooted at Path(__file__) or a module-level root
    variable built from it. A ``/ <name>`` join where ``<name>`` is a local
    string constant joins each value; an unresolvable name (e.g. a pack_id read
    from a manifest) expands over the directories that actually exist."""
    if isinstance(node, ast.Name):
        return list(roots[node.id]) if node.id in roots else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _resolve(node.left, here, roots, consts)
        if left is None:
            return None
        r = node.right
        if isinstance(r, ast.Constant) and isinstance(r.value, str):
            return [p / r.value for p in left]
        if isinstance(r, ast.Name) and r.id in consts:
            return [p / v for p in left for v in consts[r.id]]
        if isinstance(r, ast.Name):
            return [c for p in left if p.is_dir() for c in sorted(p.iterdir()) if c.is_dir()]
        return None
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name) and f.id == "Path" and len(node.args) == 1:
            a = node.args[0]
            if isinstance(a, ast.Name) and a.id == "__file__":
                return [here]
            return None
        if isinstance(f, ast.Attribute) and f.attr == "resolve" and not node.args:
            return _resolve(f.value, here, roots, consts)
        return None
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        base = _resolve(node.value, here, roots, consts)
        return [p.parent for p in base] if base is not None else None
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
        base = _resolve(node.value.value, here, roots, consts)
        idx = node.slice
        if base is not None and isinstance(idx, ast.Constant) and isinstance(idx.value, int):
            return [p.parents[idx.value] for p in base]
    return None


def _module_roots(tree: ast.Module, here: Path) -> Env:
    roots: Env = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            got = _resolve(stmt.value, here, roots, {})
            if got is not None and not any(p.suffix for p in got):
                roots[stmt.targets[0].id] = got
    return roots


def _local_consts(fn: ast.AST) -> Env:
    """Names assigned only string constants inside ``fn``."""
    vals: Dict[str, List[str]] = {}
    const_targets = set()
    for n in ast.walk(fn):
        if (
            isinstance(n, ast.Assign)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        ):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    vals.setdefault(t.id, []).append(n.value.value)
                    const_targets.add(id(t))
    # Any other binding of the name (non-constant assign, +=, annotated
    # assign, for/with/except/walrus target, a parameter) makes it non-constant.
    bad = {
        n.id for n in ast.walk(fn)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and id(n) not in const_targets
    }
    for n in ast.walk(fn):  # bindings that are not ast.Name nodes
        if isinstance(n, ast.ExceptHandler) and n.name:
            bad.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            bad |= {(al.asname or al.name).split(".")[0] for al in n.names}
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            bad |= set(n.names)
    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        a = fn.args
        bad |= {x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg] if x}
    return {k: v for k, v in vals.items() if k not in bad}


def _top_dirs(root: Path) -> set:
    return {p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")}


def iter_data_refs(root: Path, scan_dirs=SCAN_DIRS) -> Iterator[Tuple[str, int, str]]:
    """Yield (source_file, line, repo-relative referenced path)."""
    tops = _top_dirs(root)
    rroot = root.resolve()
    for d in scan_dirs:
        for py in sorted((root / d).rglob("*.py")):
            posix = py.as_posix()
            if "/tests/" in posix or "/bundle/" in posix:
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            here = py.resolve()
            roots = _module_roots(tree, here)
            seen = set()

            def _scoped(node: ast.AST, consts: Env) -> Iterator[Tuple[ast.AST, Env]]:
                # Each node is visited once, with the constants of its innermost function.
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        yield from _scoped(child, _local_consts(child))
                    else:
                        yield child, consts
                        yield from _scoped(child, consts)

            for node, consts in _scoped(tree, {}):
                targets: List[str] = []
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                    for p in _resolve(node, here, roots, consts) or []:
                        if p.suffix in SUFFIXES:
                            try:
                                targets.append(p.relative_to(rroot).as_posix())
                            except ValueError:
                                pass
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
                        targets.append(s)
                for t in targets:
                    key = (node.lineno, t)
                    if key not in seen:
                        seen.add(key)
                        yield py.relative_to(root).as_posix(), node.lineno, t


def dangling(root: Path, scan_dirs=SCAN_DIRS, gaps=OPEN_GAPS) -> List[str]:
    gap_paths = {p for p, _ in gaps}
    out = []
    for src, line, ref in iter_data_refs(root, scan_dirs):
        if ref.startswith(RUNTIME_GENERATED):
            continue
        if ref in gap_paths:
            continue
        if not (root / ref).exists():
            out.append(f"{src}:{line} -> {ref}")
    return sorted(set(out))


def gap_register_errors(root: Path, gaps, refs) -> List[str]:
    """Every register entry: exact (no glob), reasoned, still absent, still read."""
    errs = []
    for path, reason in gaps:
        if GLOB_CHARS & set(path):
            errs.append(f"glob entry: {path}")
        if not reason.strip():
            errs.append(f"no reason: {path}")
        if (root / path).exists():
            errs.append(f"gap closed, remove entry: {path}")
        if path not in refs:
            errs.append(f"not read by scanned code: {path}")
    return errs


def test_every_literal_data_path_the_code_reads_exists():
    assert dangling(ROOT) == []


def test_open_gap_register_is_exact_reasoned_and_current():
    refs = {r for _, _, r in iter_data_refs(ROOT)}
    assert gap_register_errors(ROOT, OPEN_GAPS, refs) == []


def test_steward_kit_readers_are_resolved_per_pack():
    refs = {r for _, _, r in iter_data_refs(ROOT)}
    base = "block_store/kits/private_estate_operations/steward_runtime/packs/"
    assert base + "steward_hospitality_intents_v1/mini/intents.jsonl" in refs
    assert base + "steward_fleet_open_v1/mini/vehicles.jsonl" in refs
    # pack_id is a local constant: no cross-pack phantom paths
    assert base + "steward_fleet_open_v1/mini/intents.jsonl" not in refs


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


# ── kit readers: module-level root + local pack id ─────────────────────────


def _kit_repo(tmp_path: Path, files: List[str]) -> Path:
    pk = tmp_path / "block_store" / "kits" / "k1" / "packs"
    (pk / "pa").mkdir(parents=True)
    (pk / "pb").mkdir(parents=True)
    (pk / "__init__.py").write_text(
        "from pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parent\n"
        "def load_a():\n"
        "    pack_id = 'pa'\n"
        "    return ROOT / pack_id / 'mini' / 'a.jsonl'\n"
        "def load_any(manifest):\n"
        "    pid = manifest['id']\n"
        "    return ROOT / pid / 'manifest.json'\n"
    )
    for f in files:
        (pk / f).parent.mkdir(parents=True, exist_ok=True)
        (pk / f).write_text("{}")
    return tmp_path


KP = "block_store/kits/k1/packs/"


def test_kit_reader_existing_files_pass(tmp_path):
    root = _kit_repo(tmp_path, ["pa/mini/a.jsonl", "pa/manifest.json", "pb/manifest.json"])
    refs = sorted(r for _, _, r in iter_data_refs(root, ("block_store/kits",)))
    assert refs == [KP + "pa/manifest.json", KP + "pa/mini/a.jsonl", KP + "pb/manifest.json"]
    assert dangling(root, ("block_store/kits",), ()) == []


def test_kit_reader_missing_files_fail(tmp_path):
    root = _kit_repo(tmp_path, ["pa/manifest.json"])
    assert dangling(root, ("block_store/kits",), ()) == [
        f"block_store/kits/k1/packs/__init__.py:5 -> {KP}pa/mini/a.jsonl",
        f"block_store/kits/k1/packs/__init__.py:8 -> {KP}pb/manifest.json",
    ]


@pytest.mark.parametrize("pack_id", ["pa", "pb"])
def test_async_reader_constants_are_resolved(tmp_path, pack_id):
    """An ``async def`` reader is scoped like a def: its local pack_id
    constant resolves the path it reads (the AsyncFunctionDef arm of _scoped)."""
    pk = tmp_path / "block_store" / "kits" / "k2" / "packs"
    pk.mkdir(parents=True)
    (pk / "__init__.py").write_text(
        "from pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parent\n"
        "async def load():\n"
        f"    pack_id = '{pack_id}'\n"
        "    return ROOT / pack_id / 'data.json'\n"
    )
    ref = f"block_store/kits/k2/packs/{pack_id}/data.json"
    assert [r for _, _, r in iter_data_refs(tmp_path, ("block_store/kits",))] == [ref]
    assert dangling(tmp_path, ("block_store/kits",), ()) == [
        f"block_store/kits/k2/packs/__init__.py:5 -> {ref}"
    ]


# ── open-gap register: two inputs each way ────────────────────────────────


def test_gap_entry_hides_only_its_exact_path(tmp_path):
    root = _kit_repo(tmp_path, ["pa/manifest.json", "pb/manifest.json"])
    gaps = ((KP + "pa/mini/a.jsonl", "unrecovered"),)
    assert dangling(root, ("block_store/kits",), gaps) == []
    refs = {r for _, _, r in iter_data_refs(root, ("block_store/kits",))}
    assert gap_register_errors(root, gaps, refs) == []


@pytest.mark.parametrize(
    "entry, err",
    [
        ((KP + "pa/mini/*.jsonl", "x"), "glob entry: "),
        ((KP + "pa/mini/a.jsonl", "  "), "no reason: "),
        ((KP + "pa/manifest.json", "x"), "gap closed, remove entry: "),
        ((KP + "pc/never_read.json", "x"), "not read by scanned code: "),
    ],
)
def test_gap_register_rejects_bad_entries(tmp_path, entry, err):
    root = _kit_repo(tmp_path, ["pa/manifest.json", "pb/manifest.json"])
    refs = {r for _, _, r in iter_data_refs(root, ("block_store/kits",))}
    assert err + entry[0] in gap_register_errors(root, (entry,), refs)


def test_glob_entry_does_not_hide_a_missing_file(tmp_path):
    root = _kit_repo(tmp_path, ["pa/manifest.json", "pb/manifest.json"])
    assert dangling(root, ("block_store/kits",), ((KP + "pa/mini/*.jsonl", "x"),)) != []


# ── no blanket extension rule over source dirs ────────────────────────────


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_gitignore_does_not_blanket_ignore_a_data_suffix_in_source(suffix):
    probes = [f"{d}/st7_probe{suffix}" for d in SCAN_DIRS]
    assert ignored_reads(ROOT, probes) == []


# --- repair 2: pin the runtime-exemption boundary (G2 M9) -------------------

EXPECTED_RUNTIME_GENERATED = {
    "data/storage/",
    "data/vector/",
    "data/captures/",
    "data/uploads/",
    "data/installed_container_kits.json",
    "data/domain_kit_registry.json",
    "data/block_certifications.json",
}


def test_runtime_generated_is_pinned_exactly():
    assert set(RUNTIME_GENERATED) == EXPECTED_RUNTIME_GENERATED
    assert len(RUNTIME_GENERATED) == len(EXPECTED_RUNTIME_GENERATED)


@pytest.mark.parametrize(
    "ref, expect_dangling",
    [
        ("data/uploads/blob.json", False),  # runtime-written: exempt
        ("data/fabricated_ref.json", True),  # stray non-runtime data/ read: caught
    ],
)
def test_data_dir_read_runtime_vs_stray(tmp_path, ref, expect_dangling):
    root = _mini_repo(tmp_path, ref, create=False)
    found = dangling(root, ("app",), gaps=())
    expected = [f"app/reader.py:2 -> {ref}", f"app/reader.py:3 -> {ref}"] if expect_dangling else []
    assert found == expected


# --- repair 2: the runtime ignore rules really ignore concrete paths (M17/M18)


def _concrete(entry: str) -> str:
    """A concrete runtime-written file for a RUNTIME_GENERATED entry."""
    return entry + "st7_runtime_probe.bin" if entry.endswith("/") else entry


@pytest.mark.parametrize(
    "path, ignored",
    [(_concrete(e), True) for e in sorted(EXPECTED_RUNTIME_GENERATED)]
    + [
        ("data/x.db", True),  # runtime sqlite file
        ("data/x.db-wal", True),  # sqlite write-ahead log
        ("data/x.db-shm", True),  # sqlite shared-memory file
        ("data/CEREBRUM_SKILL.md", False),  # a path the code reads: must stay tracked
    ],
)
def test_root_gitignore_on_concrete_runtime_and_source_paths(path, ignored):
    assert (ignored_reads(ROOT, [path]) == [path]) is ignored


# --- G2 N13: a name rebound to a non-constant is not a constant -------------

@pytest.mark.parametrize(
    "src, expected",
    [
        ("def f():\n    pack_id = 'alpha'\n", {"pack_id": ["alpha"]}),
        ("def f():\n    pack_id = 'alpha'\n    pack_id += suffix\n", {}),
        ("def f():\n    pack_id = 'alpha'\n    for pack_id in ids:\n        pass\n", {}),
        ("def f():\n    pack_id = 'alpha'\n    pack_id: str = other\n", {}),
        ("def f(pack_id='beta'):\n    pack_id = 'alpha'\n", {}),
        ("def f():\n    pack_id = 'alpha'\n    with open(p) as pack_id:\n        pass\n", {}),
        ("def f():\n    pack_id = 'alpha'\n    if (pack_id := other):\n        pass\n", {}),
        ("def f():\n    pack_id = 3\n", {}),
        ("def f():\n    pack_id = 'alpha'\n    pack_id = 'beta'\n", {"pack_id": ["alpha", "beta"]}),
        ("def f(pack_id, /):\n    pack_id = 'alpha'\n", {}),
        ("def f(*, pack_id):\n    pack_id = 'alpha'\n", {}),
        ("def f(*pack_id):\n    pack_id = 'alpha'\n", {}),
        ("def f(**pack_id):\n    pack_id = 'alpha'\n", {}),
        ("async def f(pack_id):\n    pack_id = 'alpha'\n", {}),
        ("def f():\n    pack_id = 'alpha'\n    try:\n        pass\n    except E as pack_id:\n        pass\n", {}),
        ("def f():\n    pack_id = 'alpha'\n    import os as pack_id\n", {}),
        ("def f():\n    pack_id = 'alpha'\n    from os import sep as pack_id\n", {}),
        ("def f():\n    global pack_id\n    pack_id = 'alpha'\n", {}),
        ("def f():\n    pack_id = 'alpha'\n    def g():\n        nonlocal pack_id\n", {}),
        ("def f():\n    pack_id = 'alpha'\n    import pack_id.sub\n", {}),
        ("def f():\n    pack_id = 'alpha'\n    import other.pack_id\n", {"pack_id": ["alpha"]}),
    ],
)
def test_local_consts_constant_vs_rebound(src, expected):
    fn = ast.parse(src).body[0]
    assert _local_consts(fn) == expected
