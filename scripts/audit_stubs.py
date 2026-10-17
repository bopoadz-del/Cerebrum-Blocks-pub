#!/usr/bin/env python3
"""Prints every hollow function as file:line name. Exit 1 if any REACHABLE
remain (i.e. any not listed in KNOWN_INCOMPLETE.md, not a decorated
abstractmethod, not a member of a typing.Protocol class, and not under
tests/). A Protocol member is an interface declaration the type checker
enforces -- like an abstractmethod it never runs, so its ``...`` body is not
a stub."""
import ast, os, sys

def load_known():
    p = "KNOWN_INCOMPLETE.md"
    if not os.path.exists(p): return set()
    out = set()
    for line in open(p, encoding="utf-8", errors="ignore"):
        line = line.strip()
        if line.startswith("- ") and "::" in line:
            out.add(line[2:].split("  ")[0].strip())
    return out

def is_abstract(node):
    for d in node.decorator_list:
        n = d.id if isinstance(d, ast.Name) else getattr(d, "attr", "")
        if n == "abstractmethod": return True
    return False

def protocol_members(tree):
    """Function nodes declared in the body of a class that subclasses Protocol."""
    out = set()
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        names = {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in cls.bases}
        if "Protocol" in names:
            out.update(id(n) for n in cls.body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return out

def hollow(node):
    body = [x for x in node.body if not (isinstance(x, ast.Expr)
            and isinstance(x.value, ast.Constant)
            and isinstance(x.value.value, str))]
    if not body: return True
    if len(body) == 1:
        b = body[0]
        if isinstance(b, ast.Pass): return True
        if isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant) \
           and b.value.value is Ellipsis: return True
        if isinstance(b, ast.Raise) and isinstance(getattr(b, "exc", None), ast.Call) \
           and isinstance(b.exc.func, ast.Name) and b.exc.func.id == "NotImplementedError":
            return True
        if isinstance(b, ast.Return) and (b.value is None
           or (isinstance(b.value, ast.Constant) and b.value.value in (None, "", 0))
           or (isinstance(b.value, ast.Dict) and not b.value.keys)
           or (isinstance(b.value, ast.List) and not b.value.elts)):
            return True
    return False

def main():
    known = load_known()
    reachable = []
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in
                   {".git","__pycache__",".venv","venv","env","node_modules","generated",
                    "bundle","factory_outputs","deployments","site-packages",".postgres"}]
        for f in files:
            if not f.endswith(".py"): continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, ".").replace(os.sep, "/")  # portable keys
            try: tree = ast.parse(open(p, encoding="utf-8", errors="ignore").read())
            except SyntaxError: continue
            in_tests = rel.startswith("tests/") or "/tests/" in rel
            interface = protocol_members(tree)
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not hollow(n) or is_abstract(n) or id(n) in interface: continue
                    tag = f"{rel}:{n.lineno} {n.name}"
                    key = f"{rel} :: {n.name}"
                    if in_tests:  # harness helpers are allowed
                        continue
                    if key in known:  # registered optional/roadmap
                        continue
                    reachable.append(tag)
    if reachable:
        sys.stdout.write("REACHABLE HOLLOW FUNCTIONS (must implement or register):\n")
        for t in reachable: sys.stdout.write("  " + t + "\n")
        sys.stdout.write(f"TOTAL: {len(reachable)}\n")
        sys.exit(1)
    sys.stdout.write("NO REACHABLE HOLLOW FUNCTIONS.\n")

if __name__ == "__main__":
    main()
