#!/usr/bin/env python3
"""Fail-closed dependency audit: pip-audit, no bare ignore.

Dual-registered with <private-repo> ``scripts/dep_audit.py`` (Factory).
Shared rules: every remaining advisory needs a dated note and a test twin;
adjudicate against declared Requires-Dist, not a scanner summary; never a
bare ``pip-audit --ignore-vuln``.

A remaining advisory is allowed only when a dated registry note still
matches the live finding (empty fix_versions, or the installed pin
already satisfies the published fix).

Usage:
  python3 scripts/dep_audit.py
  python3 scripts/dep_audit.py --python
  python3 scripts/dep_audit.py --pip-json PATH
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = (
    REPO_ROOT / "docs" / "security" / "dependency-adjudications" / "registry.json"
)
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
REQUIREMENTS = REPO_ROOT / "requirements.txt"

# Forbidden in workflows: a suppression that is not the registry.
BARE_IGNORE_MARKERS = (
    "--ignore-vuln",
    "npm audit --ignore",
    "npm audit --audit-level=none",
)


class Finding:
    __slots__ = ("ecosystem", "package", "version", "vuln_id", "aliases", "fix_versions")

    def __init__(
        self,
        *,
        ecosystem: str,
        package: str,
        version: str,
        vuln_id: str,
        aliases: Iterable[str] = (),
        fix_versions: Iterable[str] = (),
    ) -> None:
        self.ecosystem = ecosystem
        self.package = package
        self.version = version
        self.vuln_id = vuln_id
        self.aliases = tuple(sorted({a for a in aliases if a}))
        self.fix_versions = tuple(v for v in fix_versions if v)

    @property
    def keys(self) -> set[str]:
        return {self.vuln_id, *self.aliases}


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"dep-audit: missing registry {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def registry_index(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map every id and alias to its row. Duplicate keys must agree."""
    index: dict[str, dict[str, Any]] = {}
    for row in registry.get("adjudications") or []:
        keys = [row["id"], *(row.get("aliases") or [])]
        for key in keys:
            existing = index.get(key)
            if existing is not None and existing["id"] != row["id"]:
                raise ValueError(
                    f"dep-audit: {key} maps to both {existing['id']} and {row['id']}"
                )
            index[key] = row
    return index


def findings_from_pip_audit(data: dict[str, Any] | list) -> list[Finding]:
    deps = data if isinstance(data, list) else data.get("dependencies") or []
    seen: set[tuple[str, str, str]] = set()
    out: list[Finding] = []
    for dep in deps:
        name = str(dep.get("name") or dep.get("package") or "")
        version = str(dep.get("version") or dep.get("installed_version") or "")
        for vuln in dep.get("vulns") or dep.get("vulnerabilities") or []:
            vid = str(vuln.get("id") or "")
            if not name or not vid:
                continue
            key = (name.lower(), version, vid)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                Finding(
                    ecosystem="pip",
                    package=name,
                    version=version,
                    vuln_id=vid,
                    aliases=vuln.get("aliases") or [],
                    fix_versions=vuln.get("fix_versions") or vuln.get("fixed_versions") or [],
                )
            )
    return out


def _note_ok(row: dict[str, Any], repo: Path = REPO_ROOT) -> list[str]:
    errors: list[str] = []
    note = str(row.get("note") or "")
    dated = str(row.get("date") or "")
    vid = str(row.get("id") or "")
    if not dated:
        errors.append(f"{vid}: registry row has no date")
    else:
        try:
            date.fromisoformat(dated)
        except ValueError:
            errors.append(f"{vid}: date {dated!r} is not ISO YYYY-MM-DD")
    if not note:
        errors.append(f"{vid}: registry row has no note path")
        return errors
    path = repo / note
    if not path.is_file():
        errors.append(f"{vid}: note missing: {note}")
        return errors
    text = path.read_text(encoding="utf-8")
    if vid not in text:
        errors.append(f"{vid}: note {note} does not name the advisory id")
    if dated and dated not in text:
        errors.append(f"{vid}: note {note} does not name the adjudication date")
    if "Decision:" not in text and "decision" not in text.lower():
        errors.append(f"{vid}: note {note} has no decision")
    return errors


def evaluate(
    findings: Iterable[Finding],
    registry: dict[str, Any],
    *,
    repo: Path = REPO_ROOT,
) -> list[str]:
    """Return human-readable failures. Empty means the resolve is allowed."""
    errors: list[str] = []
    index = registry_index(registry)
    for row in registry.get("adjudications") or []:
        errors.extend(_note_ok(row, repo))
        if str(row.get("decision") or "") == "suppress":
            errors.append(f"{row.get('id')}: decision 'suppress' is a bare suppression")
    for finding in findings:
        row = next((index[k] for k in finding.keys if k in index), None)
        if row is None:
            errors.append(
                f"undocumented {finding.ecosystem} advisory {finding.vuln_id} "
                f"in {finding.package}=={finding.version}. Write a dated note "
                f"+ registry row, or upgrade. Never --ignore-vuln."
            )
            continue
        decision = str(row.get("decision") or "")
        if decision == "accept_constrained":
            ev = row.get("evidence") or {}
            if ev.get("kind") != "declared_requires_dist":
                errors.append(
                    f"{row['id']}: accept_constrained needs evidence.kind="
                    f"declared_requires_dist (got {ev.get('kind')!r})"
                )
            if not ev.get("constraining_package") or not ev.get("constraint"):
                errors.append(
                    f"{row['id']}: accept_constrained must name constraining_package "
                    f"and constraint from Requires-Dist"
                )
            continue
        if finding.fix_versions and decision == "accept_until_fix":
            errors.append(
                f"stale adjudication {row['id']} ({finding.vuln_id}): "
                f"pip-audit now lists fix_versions={list(finding.fix_versions)}. "
                f"Upgrade {finding.package} or rewrite the {row.get('date')} note. "
                f"Do not keep a silent ignore."
            )
    return errors


def pip_audit_argv(requirements: Path) -> list[str]:
    """Audit the store pin file, not the runner's site-packages.

    A local-env scan on GitHub Actions reports toolchain packages
    (setuptools on the 3.11 image) that are not in ``requirements.txt``.
    ``-r`` is the Linux resolve this job adjudicates. Do not replace it
    with a bare ``--ignore-vuln``.
    """
    return [
        sys.executable,
        "-m",
        "pip_audit",
        "-r",
        str(requirements),
        "--format",
        "json",
        "--progress-spinner",
        "off",
    ]


def run_pip_audit(cwd: Path | None = None) -> dict[str, Any]:
    root = cwd or REPO_ROOT
    requirements = root / "requirements.txt"
    proc = subprocess.run(
        pip_audit_argv(requirements),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    # pip-audit exits 1 when it finds vulns; that is the input, not the gate.
    if proc.returncode not in (0, 1):
        raise RuntimeError(
            f"pip-audit failed (exit {proc.returncode}): {proc.stderr or proc.stdout}"
        )
    raw = proc.stdout.strip() or "{}"
    return json.loads(raw)


def workflow_has_bare_ignore(text: str) -> list[str]:
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        code = line.split("#", 1)[0]
        for marker in BARE_IGNORE_MARKERS:
            if marker in code:
                hits.append(f"{CI_YML.name}:{i}: {marker}")
    return hits


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--python", action="store_true", help="Run pip-audit (default).")
    parser.add_argument("--pip-json", type=Path, help="Synthetic pip-audit JSON.")
    parser.add_argument(
        "--registry",
        type=Path,
        default=REGISTRY_PATH,
        help="Adjudication registry (default: in-repo).",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=REPO_ROOT,
        help="Repo root (notes are resolved from here).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo
    try:
        registry = load_registry(args.registry)
    except Exception as exc:
        print(f"dep-audit: {exc}", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    try:
        if args.pip_json:
            data = json.loads(args.pip_json.read_text(encoding="utf-8"))
        else:
            data = run_pip_audit(repo)
        findings.extend(findings_from_pip_audit(data))
    except Exception as exc:
        print(f"dep-audit: scanner failed: {exc}", file=sys.stderr)
        return 1

    errors = evaluate(findings, registry, repo=repo)
    ci_path = repo / ".github" / "workflows" / "ci.yml"
    if ci_path.is_file():
        errors.extend(
            f"bare suppression {h}"
            for h in workflow_has_bare_ignore(ci_path.read_text(encoding="utf-8"))
        )

    if errors:
        for line in errors:
            print(f"dep-audit: {line}", file=sys.stderr)
        return 1
    pip_n = sum(1 for f in findings if f.ecosystem == "pip")
    adj = len(registry.get("adjudications") or [])
    print(
        f"ok: dep-audit python={pip_n} "
        f"adjudications={adj} (dated notes + twins, no bare ignore)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
