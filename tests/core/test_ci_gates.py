"""CI gates and intentional-absence logging.

Hardening guarantees pinned here:

* The backend CI job actually runs the stub audit and the secret scan —
  both scripts existed but were never wired into the workflow, so their
  gates had never fired on a PR.
* The lockfile-consistency job is scheduled and required. A checker that
  is not in the workflow is a skip; a job with continue-on-error is the
  same skip under another name.
* A vector store deliberately deployed without ``DATABASE_URL`` (the
  store service runs no RAG demo flows) logs its absence at INFO, not
  WARNING. Intentional configuration must not read as a fault in the
  boot log.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_ci_workflow_runs_stub_audit_and_secret_scan():
    workflow = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "python scripts/audit_stubs.py" in workflow, (
        "CI must run the stub audit (implement-or-register gate)"
    )
    assert "python scripts/scan_secrets.py" in workflow, (
        "CI must run the secret scan on non-test paths"
    )
    assert "python scripts/census_registry.py" in workflow, (
        "CI must run the B04 registry census"
    )
    assert "python scripts/scan_exception_pass.py" in workflow, (
        "CI must run the B07 silent-return scanner"
    )
    assert "python scripts/dep_audit.py" in workflow, (
        "CI must run the fail-closed pip-audit wrapper"
    )
    assert "--ignore-vuln" not in workflow
    assert "pip-audit (report-only until the pins are resolved)" not in workflow


def _job_body(workflow: str, job_id: str) -> str:
    marker = f"  {job_id}:"
    start = workflow.find(marker)
    assert start != -1, f"CI is missing required job {job_id}"
    rest = workflow[start + len(marker) :]
    end = len(rest)
    for i, line in enumerate(rest.splitlines()[1:], start=1):
        if line.startswith("  ") and not line.startswith("   ") and line.endswith(":"):
            end = sum(len(part) + 1 for part in rest.splitlines()[:i])
            break
    return rest[:end]


def test_ci_workflow_requires_lockfile_consistency_job():
    """Census fence: the lockfile gate is scheduled and is not allowed to fail.

    A checker that is not in the workflow is a skip. A job with
    continue-on-error is the same skip under another name.
    """
    workflow = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    body = _job_body(workflow, "lockfile-consistency")
    assert "python scripts/check_lockfile_consistency.py" in body
    assert "tests/test_lockfile_consistency.py" in body
    assert "continue-on-error:" not in body
    assert "allow_failure:" not in body


@pytest.mark.asyncio
async def test_missing_database_url_logs_info_not_warning(monkeypatch, caplog):
    from app.core import vector_store

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(vector_store, "_pool", None)

    with caplog.at_level(logging.INFO, logger="app.core.vector_store"):
        pool = await vector_store.init_pool()

    assert pool is None
    records = [r for r in caplog.records if "DATABASE_URL" in r.getMessage()]
    assert records, "init_pool must still announce the intentional absence"
    assert all(r.levelno == logging.INFO for r in records), (
        "intentional no-DATABASE_URL configuration must log at INFO, "
        f"got: {[(r.levelname, r.getMessage()) for r in records]}"
    )
    assert "expected" in records[0].getMessage()


def test_stub_audit_exempts_protocol_members_only(tmp_path, monkeypatch):
    """A typing.Protocol member is an interface declaration (like an
    abstractmethod); the same ``...`` body anywhere else is still a stub."""
    import subprocess
    import sys

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "iface.py").write_text(
        "from typing import Protocol\n"
        "class ZorblatStore(Protocol):\n"
        "    def read(self, key: str) -> str: ...\n",
        encoding="utf-8",
    )
    script = _REPO_ROOT / "scripts" / "audit_stubs.py"
    ok = subprocess.run([sys.executable, str(script)], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert ok.returncode == 0, ok.stdout

    (tmp_path / "pkg" / "impl.py").write_text(
        "class ZorblatImpl:\n    def read(self, key: str) -> str: ...\n", encoding="utf-8"
    )
    bad = subprocess.run([sys.executable, str(script)], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert bad.returncode == 1 and "pkg/impl.py" in bad.stdout and "iface.py" not in bad.stdout
