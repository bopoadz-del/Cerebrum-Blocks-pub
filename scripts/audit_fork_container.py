#!/usr/bin/env python3
"""Structural audit of The Fork construction container for migration manifest."""
import ast
import json
import re
from pathlib import Path

FORK = Path(r"C:\Users\<owner>\The_Fork")
CB = Path(r"C:\Users\<owner>\Cerebrum-Blocks")


def file_stats(p: Path) -> dict:
    if not p.exists():
        return {"exists": False}
    src = p.read_text(encoding="utf-8", errors="replace")
    return {
        "exists": True,
        "path": str(p),
        "lines": src.count("\n") + 1,
        "bytes": len(src.encode("utf-8")),
    }


def class_methods(p: Path, class_name: str) -> list[str]:
    src = p.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            out = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    prefix = "async " if isinstance(item, ast.AsyncFunctionDef) else ""
                    out.append(prefix + item.name)
            return out
    return []


def top_imports(p: Path) -> list[str]:
    src = p.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    out = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append(a.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for a in node.names:
                out.append(f"from {mod} import {a.name}")
    return out


def string_refs(p: Path) -> dict:
    src = p.read_text(encoding="utf-8", errors="replace")
    patterns = [
        "construction_knowledge",
        "ConstructionKnowledge",
        "construction_expert",
        "construction_evm",
        "procedures_db",
        "construction_kb",
        "construction_constants",
        "construction_types",
        "BLOCK_REGISTRY",
        "_resolve_block",
        "UniversalContainer",
        "system_prompt_file",
        "use_rag",
    ]
    return {k: len(re.findall(re.escape(k), src)) for k in patterns}


def extract_requires(p: Path) -> list[str]:
    src = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"requires\s*=\s*\[(.*?)\]", src, re.DOTALL)
    if not m:
        return []
    return re.findall(r"['\"]([\w_]+)['\"]", m.group(1))


def extract_get_actions(p: Path) -> list[str]:
    src = p.read_text(encoding="utf-8", errors="replace")
    idx = src.find("def get_actions")
    if idx < 0:
        return []
    chunk = src[idx : idx + 120000]
    return sorted(set(re.findall(r'"action"\s*:\s*"([\w_]+)"', chunk)))


def knowledge_symbols(p: Path) -> dict:
    src = p.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    funcs, classes, assigns = [], [], []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            funcs.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigns.append(t.id)
    return {"functions": funcs, "classes": classes, "module_constants": assigns}


def block_refs_in_container(p: Path) -> dict[str, int]:
    src = p.read_text(encoding="utf-8", errors="replace")
    names = re.findall(r'_resolve_block\(\s*["\']([\w_]+)["\']', src)
    names += re.findall(r'_get_(\w+)_block', src)
    counts: dict[str, int] = {}
    for n in names:
        counts[n] = counts.get(n, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def main():
    fork_container = FORK / "app/containers/construction.py"
    fork_knowledge = FORK / "app/core/construction_knowledge.py"
    cb_container = CB / "app/containers/construction.py"
    cb_knowledge = CB / "app/core/construction_knowledge.py"

    methods = class_methods(fork_container, "ConstructionContainer")
    public_actions = [m for m in methods if not m.startswith("_") and m not in ("process", "get_actions")]

    report = {
        "source": "https://github.com/bopoadz-del/The_Fork (main)",
        "fork_container": file_stats(fork_container),
        "cerebrum_container": file_stats(cb_container),
        "fork_knowledge": file_stats(fork_knowledge),
        "cerebrum_knowledge": file_stats(cb_knowledge),
        "imports": top_imports(fork_container),
        "requires_blocks": extract_requires(fork_container),
        "method_count": len(methods),
        "public_methods": public_actions,
        "private_helper_count": len(methods) - len(public_actions) - 2,
        "string_refs": string_refs(fork_container),
        "block_delegate_refs": block_refs_in_container(fork_container),
        "get_actions": extract_get_actions(fork_container),
        "knowledge": knowledge_symbols(fork_knowledge),
        "fork_files": {
            "prompts": [str(p.relative_to(FORK)) for p in (FORK / "app/prompts").glob("*construction*")],
            "data": [str(p.relative_to(FORK)) for p in (FORK / "app/data").rglob("*") if "procedure" in p.name.lower()],
            "knowledge_json": [str(p.relative_to(FORK)) for p in (FORK / "app/knowledge").glob("*construction*")],
        },
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
