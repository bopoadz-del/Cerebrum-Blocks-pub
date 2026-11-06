"""Import closure: a block ships only against modules the Store ships.

Every ``app.core.<mod>`` / ``app.blocks.<mod>`` import (module-level and
function-level) in a block source file must resolve to a file in the
Store's own tree. An import the Store does not ship is a publish gate:
a block that reaches a platform referencing code that is not in the
Store cannot be cloned by any factory build.

Everything here derives from the tree: the block files come from the
glob, the imports come from the AST, and resolution is a filesystem
lookup. No block name, module name or path is spelled anywhere -- the
scan_hardwiring gate stays clean by construction.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Source globs whose files are graded. Derived, never named.
_BLOCK_GLOBS = (
    "app/blocks/*.py",
    "block_store/kits/*/bundle/app/blocks/*.py",
    "block_store/kits/*/bundle/app/core/*.py",
)


def _imports(py: pathlib.Path):
    """Every ``app.*`` import the file makes, at any nesting level."""
    tree = ast.parse(py.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            yield node.module
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app."):
                    yield alias.name


def _exists(module: str) -> bool:
    """The import resolves when a module file or a package __init__ sits at
    its dotted path inside the Store tree."""
    base = ROOT.joinpath(*module.split("."))
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def _graded_files():
    out: list = []
    for pattern in _BLOCK_GLOBS:
        out.extend(sorted(ROOT.glob(pattern)))
    return out


@pytest.mark.parametrize("source", _graded_files(), ids=lambda p: p.as_posix())
def test_block_imports_are_closed_inside_the_store(source):
    missing = sorted({m for m in _imports(source) if not _exists(m)})
    assert not missing, (
        f"{source.as_posix()} imports modules the Store does not ship: {missing}"
    )
