#!/usr/bin/env python3
"""Fail the build on ``except Exception: pass`` (body is only Pass).

Ported from The_Fork (READ-ONLY). Same detector, same --list-returns
shape. Bare ``except: pass`` is ruff E722 / S110. This twin is the typed
form those selectors do not cover: ``except Exception: pass`` and
``except Exception as <name>: pass``.

The RETURN twin baselines ``except <anything>: return <empty>`` by
file:line and fails on the N+1th, so the count can only fall.

Walks the same tree as ``scripts/audit_stubs.py`` (skips ``tests/`` and
vendor dirs). Exit 1 with a file:line list if any remain that are not in
the named allowlist.

Regenerate the return baseline after a cleanup:
  python scripts/scan_exception_pass.py --list-returns
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

# Union of this repo's audit_stubs skip set and The_Fork's scanner skip
# set. ``bundle/`` is published kit copies — scanning them would baseline
# the same swallow twice.
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "generated",
    "bundle",
    "factory_outputs",
    "deployments",
    "site-packages",
    ".postgres",
    ".worktrees",
    ".claude",
    "dist",
    "build",
    ".pytest_cache",
}

# Keys are "relative/path.py:lineno". Value is the named reason this
# Exception+pass is allowed to stay. Empty is the goal.
ALLOWLIST: dict[str, str] = {
    "app/blocks/agent_swarm.py:723": "baseline 2026-09-11",
    "app/blocks/agent_swarm.py:745": "baseline 2026-09-11",
    "app/blocks/async_processor.py:177": "baseline 2026-09-11",
    "app/blocks/bim_extractor.py:226": "baseline 2026-09-11",
    "app/blocks/bim_extractor.py:236": "baseline 2026-09-11",
    "app/blocks/bim_extractor.py:252": "baseline 2026-09-11",
    "app/blocks/capture.py:521": "baseline 2026-09-11",
    "app/blocks/capture.py:543": "baseline 2026-09-11",
    "app/blocks/capture.py:560": "baseline 2026-09-11",
    "app/blocks/context_broker.py:176": "baseline 2026-09-11",
    "app/blocks/document_engine/parsers/pdf_parser.py:34": "baseline 2026-09-11",
    "app/blocks/document_engine/parsers/pdf_parser.py:41": "baseline 2026-09-11",
    "app/blocks/document_engine/parsers/pdf_parser.py:48": "baseline 2026-09-11",
    "app/blocks/image.py:113": "baseline 2026-09-11",
    "app/blocks/jetson_gateway.py:61": "baseline 2026-09-11",
    "app/blocks/knowledge.py:412": "baseline 2026-09-11",
    "app/blocks/knowledge.py:427": "baseline 2026-09-11",
    "app/blocks/knowledge.py:442": "baseline 2026-09-11",
    "app/blocks/learning_engine.py:108": "baseline 2026-09-11",
    "app/blocks/learning_engine.py:228": "baseline 2026-09-11",
    "app/blocks/library_container.py:256": "baseline 2026-09-11",
    "app/blocks/mcp_consumer.py:81": "baseline 2026-09-11",
    "app/blocks/ocr.py:170": "baseline 2026-09-11",
    "app/blocks/ocr.py:350": "baseline 2026-09-11",
    "app/blocks/pdf_v2.py:131": "baseline 2026-09-11",
    "app/blocks/recommendation_template.py:57": "baseline 2026-09-11",
    "app/blocks/smart_orchestrator.py:283": "baseline 2026-09-11",
    "app/blocks/traffic_manager.py:126": "baseline 2026-09-11",
    "app/blocks/validation.py:510": "baseline 2026-09-11",
    "app/blocks/validation.py:536": "baseline 2026-09-11",
    "app/blocks/workbench.py:237": "baseline 2026-09-11",
    "app/containers/construction/__init__.py:1197": "baseline 2026-09-11",
    "app/containers/construction/__init__.py:372": "baseline 2026-09-11",
    "app/containers/construction/__init__.py:45": "baseline 2026-09-11",
    "app/containers/construction/__init__.py:772": "baseline 2026-09-11",
    "app/containers/construction/boq.py:687": "baseline 2026-09-11",
    "app/containers/construction/documents.py:101": "baseline 2026-09-11",
    "app/containers/construction/documents.py:114": "baseline 2026-09-11",
    "app/containers/construction/documents.py:143": "baseline 2026-09-11",
    "app/containers/construction/documents.py:176": "baseline 2026-09-11",
    "app/containers/construction/documents.py:185": "baseline 2026-09-11",
    "app/containers/construction/schedule.py:1070": "baseline 2026-09-11",
    "app/containers/construction/schedule.py:136": "baseline 2026-09-11",
    "app/containers/construction/schedule.py:267": "baseline 2026-09-11",
    "app/core/video_store.py:103": "baseline 2026-09-11",
    "app/dependencies.py:90": "baseline 2026-09-11",
    "app/routers/upload.py:303": "baseline 2026-09-11",
    "app/routers/upload.py:380": "baseline 2026-09-11",
    "block_store/containers/libraries.py:298": "baseline 2026-09-11",
    "block_store/containers/security.py:260": "baseline 2026-09-11",
    "block_store/containers/security.py:291": "baseline 2026-09-11",
    "block_store/kits/universal_kernel/wave1/rate_limit_guard/code.py:176": "baseline 2026-09-11",
    "block_store/kits/universal_kernel/wave2/secure_ingestion/code.py:72": "baseline 2026-09-11",
    "block_store/recommendation_template.py:204": "baseline 2026-09-11",
}


# The RETURN twin's baseline. Keys are "relative/path.py:lineno"; the value is
# why the site may stay. Every entry has the same reason -- it was here before
# the scanner was -- and the count may only fall.
#
# The twin exists to stop the next site, not to pretend the remainder are fine.
# Each closes one of two ways: log what failed and keep returning empty (the
# caller genuinely tolerates nothing), or raise a typed outcome (a decision
# path, where "nothing there" and "it broke" must not be the same answer).
#
# Regenerate after a cleanup:  python scripts/scan_exception_pass.py --list-returns
RETURN_ALLOWLIST: dict[str, str] = {
    "app/blocks/agency_hierarchy.py:382": "baseline 2026-09-11",
    "app/blocks/bim_extractor.py:267": "baseline 2026-09-11",
    "app/blocks/bim_extractor.py:281": "baseline 2026-09-11",
    "app/blocks/bordereaux_ingest.py:380": "baseline 2026-09-11",
    "app/blocks/capture.py:596": "baseline 2026-09-11",
    "app/blocks/context_broker.py:192": "baseline 2026-09-11",
    "app/blocks/core/action_contract/registry.py:129": "baseline 2026-09-11",
    "app/blocks/distribution_analytics.py:363": "baseline 2026-09-11",
    "app/blocks/hkia_gn16_rules.py:688": "baseline 2026-09-11",
    "app/blocks/image.py:137": "baseline 2026-09-11",
    "app/blocks/medical_ehr_connector.py:201": "baseline 2026-09-11",
    "app/blocks/ocr.py:305": "baseline 2026-09-11",
    "app/blocks/ocr.py:307": "baseline 2026-09-11",
    "app/blocks/ocr.py:322": "baseline 2026-09-11",
    "app/blocks/producer_record.py:305": "baseline 2026-09-11",
    "app/blocks/secrets.py:260": "baseline 2026-09-11",
    "app/blocks/vector_search.py:33": "baseline 2026-09-11",
    "app/containers/construction/__init__.py:1071": "baseline 2026-09-11",
    "app/containers/construction/__init__.py:1201": "baseline 2026-09-11",
    "app/containers/construction/__init__.py:154": "baseline 2026-09-11",
    "app/containers/construction/__init__.py:465": "baseline 2026-09-11",
    "app/containers/construction/__init__.py:472": "baseline 2026-09-11",
    "app/containers/construction/__init__.py:927": "baseline 2026-09-11",
    "app/containers/construction/boq.py:535": "baseline 2026-09-11",
    "app/containers/construction/helpers.py:66": "baseline 2026-09-11",
    "app/containers/construction/schedule.py:119": "baseline 2026-09-11",
    "app/containers/construction/schedule.py:123": "baseline 2026-09-11",
    "app/core/auth.py:103": "baseline 2026-09-11",
    "app/core/backup_scheduler.py:93": "baseline 2026-09-11",
    "app/core/block_validation.py:185": "baseline 2026-09-11",
    "app/core/cache_wrapper.py:23": "baseline 2026-09-11",
    "app/core/cache_wrapper.py:35": "baseline 2026-09-11",
    "app/core/cache_wrapper.py:46": "baseline 2026-09-11",
    "app/core/construction_knowledge.py:277": "baseline 2026-09-11",
    "app/core/file_crypto.py:87": "baseline 2026-09-11",
    "app/core/formula_definitions.py:131": "baseline 2026-09-11",
    "app/core/logging_config.py:240": "baseline 2026-09-11",
    "app/core/mlflow_tracker.py:64": "baseline 2026-09-11",
    "app/core/sandbox.py:302": "baseline 2026-09-11",
    # app/core/vector_store.py:159 was `except Exception: return {}` in
    # ``_json_meta``. It now logs which chunk failed to decode and why, so it is
    # no longer a silent empty return and no longer needs a line here. Removed
    # rather than moved: the baseline only ever gets smaller.
    "app/dependencies.py:125": "baseline 2026-09-11",
    "app/lib/pm_computations.py:340": "baseline 2026-09-11",
    "app/routers/health.py:140": "baseline 2026-09-11",
    "app/routers/health.py:142": "baseline 2026-09-11",
    "app/routers/health.py:157": "baseline 2026-09-11",
    "block_registry/run.py:24": "baseline 2026-09-11",
    "block_store/containers/libraries.py:388": "baseline 2026-09-11",
    "block_store/containers/reasoning_engine.py:309": "baseline 2026-09-11",
    "block_store/kits/_template/cli/cerebrum_cli/config.py:37": "baseline 2026-09-11",
    "block_store/kits/universal_kernel/wave1/identity/code.py:71": "baseline 2026-09-11",
    "block_store/kits/universal_kernel/wave2/grounded_answer/code.py:82": "baseline 2026-09-11",
    "cli/cerebrum_cli/config.py:47": "baseline 2026-09-11",
    "scripts/check_lockfile_consistency.py:99": "baseline 2026-09-11",
    "scripts/lane2_conformance.py:178": "baseline 2026-09-11",
    "scripts/lane2_conformance.py:349": "baseline 2026-09-11",
    "scripts/measure_brief_scope.py:174": "baseline 2026-09-11",
    "scripts/pipeline_kit.py:92": "baseline 2026-09-11",
    "scripts/regenerate_safe_adapters.py:90": "baseline 2026-09-11",
    "scripts/review_kit.py:78": "baseline 2026-09-11",

}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _catches_exception(handler: ast.ExceptHandler) -> bool:
    """True only for ``except Exception`` (optionally ``as name``).

    Bare ``except:`` is ruff E722. Narrow types (OSError, …) are a
    deliberate cleanup. ``BaseException`` is a different, worse bug.
    """
    t = handler.type
    if t is None:
        return False
    names = t.elts if isinstance(t, ast.Tuple) else [t]
    for n in names:
        if isinstance(n, ast.Name) and n.id == "Exception":
            return True
        if isinstance(n, ast.Attribute) and n.attr == "Exception":
            return True
    return False


def _body_is_only_pass(handler: ast.ExceptHandler) -> bool:
    body = [
        n
        for n in handler.body
        if not (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        )
    ]
    return len(body) == 1 and isinstance(body[0], ast.Pass)


def exception_pass_lines(tree: ast.AST) -> list[int]:
    """Line numbers of ``except Exception: pass`` / ``as <name>: pass``."""
    out: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ExceptHandler)
            and _catches_exception(node)
            and _body_is_only_pass(node)
        ):
            out.append(node.lineno)
    return out


#: The empty values a handler can hand back instead of an outcome.
_EMPTY_CONSTANTS = (None, "", 0, False)


def _returns_only_an_empty_value(handler: ast.ExceptHandler) -> bool:
    """True when the handler's only statement returns None / {} / [] / '' / 0."""
    body = [
        n
        for n in handler.body
        if not (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        )
    ]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return False
    value = body[0].value
    if value is None:  # bare `return`
        return True
    if isinstance(value, ast.Constant) and value.value in _EMPTY_CONSTANTS:
        return True
    if isinstance(value, ast.Dict) and not value.keys:
        return True
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)) and not value.elts:
        return True
    return False


def exception_return_lines(tree: ast.AST) -> list[int]:
    """Line numbers of ``except <anything>:`` whose body is only an empty return.

    ANY exception type counts here, unlike the pass-twin which is scoped to
    ``Exception``: swallowing ``OSError`` into ``return None`` is the same
    invisible degradation as swallowing ``Exception``, and the caller cannot
    tell "nothing there" from "the lookup failed" in either case.

    One statement only. A handler that logs and then returns empty has made
    the degradation visible, which is the whole ask -- it is not flagged.
    """
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and _returns_only_an_empty_value(node)
    )


def iter_python_files(root: Path | None = None):
    """Yield (relpath, absolute path) for every scanned ``.py`` file.

    ``relpath`` uses forward slashes so Windows and POSIX report the same
    file:line keys (the same normalisation ``audit_stubs.py`` documents).
    """
    root = Path(root) if root is not None else repo_root()
    root = root.resolve()
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if not name.endswith(".py"):
                continue
            abs_path = Path(dirpath) / name
            rel = abs_path.relative_to(root).as_posix()
            if rel.startswith("tests/") or "/tests/" in rel:
                continue
            yield rel, abs_path


def scan(root: Path | None = None) -> list[str]:
    """Return ``file:line`` findings not covered by a named ALLOWLIST entry."""
    findings: list[str] = []
    root = Path(root) if root is not None else repo_root()
    for rel, abs_path in iter_python_files(root):
        try:
            tree = ast.parse(abs_path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for lineno in exception_pass_lines(tree):
            key = f"{rel}:{lineno}"
            reason = ALLOWLIST.get(key)
            if reason:
                continue
            findings.append(key)
    return findings


def scan_returns(root: Path | None = None) -> list[str]:
    """``file:line`` for every empty-return handler not in RETURN_ALLOWLIST."""
    findings: list[str] = []
    root = Path(root) if root is not None else repo_root()
    for rel, abs_path in iter_python_files(root):
        try:
            tree = ast.parse(abs_path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for lineno in exception_return_lines(tree):
            key = f"{rel}:{lineno}"
            if RETURN_ALLOWLIST.get(key):
                continue
            findings.append(key)
    return findings


def all_return_sites(root: Path | None = None) -> list[str]:
    """Every empty-return handler, allowlisted or not. Backs --list-returns."""
    out: list[str] = []
    root = Path(root) if root is not None else repo_root()
    for rel, abs_path in iter_python_files(root):
        try:
            tree = ast.parse(abs_path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        out += [f"{rel}:{n}" for n in exception_return_lines(tree)]
    return sorted(out)


def main() -> int:
    if "--list-returns" in sys.argv:
        # Paste-ready RETURN_ALLOWLIST body, for regenerating after a cleanup.
        for key in all_return_sites():
            sys.stdout.write('    "%s": "baseline 2026-09-11",\n' % key)
        return 0

    rc = 0
    findings = scan()
    if findings:
        sys.stdout.write(
            "SILENT except Exception: pass (log it or name a reason in "
            "ALLOWLIST):\n"
        )
        for item in findings:
            sys.stdout.write(f"  {item}\n")
        sys.stdout.write(f"TOTAL: {len(findings)}\n")
        rc = 1
    else:
        sys.stdout.write("NO silent except Exception: pass handlers.\n")

    returns = scan_returns()
    if returns:
        sys.stdout.write(
            "SILENT except -> empty return. Log what failed, or raise a typed "
            "outcome; do not add to RETURN_ALLOWLIST:\n"
        )
        for item in returns:
            sys.stdout.write(f"  {item}\n")
        sys.stdout.write(f"TOTAL: {len(returns)}\n")
        rc = 1
    else:
        sys.stdout.write(
            f"RETURN: 0 new ({len(RETURN_ALLOWLIST)} baselined).\n"
        )
    return rc


if __name__ == "__main__":
    sys.exit(main())
