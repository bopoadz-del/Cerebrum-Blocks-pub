"""Dependency-audit twins: dated note + live constraint, never a bare ignore.

The previous Factory miss was a workplan that invented a ``click`` ceiling.
``gTTS 2.5.4`` really declares ``click<8.2`` — and that package IS a Store
runtime pin (voice block). These tests read declared Requires-Dist, not a
scanner blurb. The published click fix was 8.3.3, not a ceiling.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import date
from importlib import metadata
from pathlib import Path

import pytest
from packaging.version import Version

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "dep_audit.py"
REGISTRY = (
    REPO_ROOT / "docs" / "security" / "dependency-adjudications" / "registry.json"
)
README = (
    REPO_ROOT / "docs" / "security" / "dependency-adjudications" / "README.md"
)
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
REQ = REPO_ROOT / "requirements.txt"
LOCK = REPO_ROOT / "requirements.lock"


def _load_script():
    spec = importlib.util.spec_from_file_location("dep_audit", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def audit():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    return _load_script()


def _run(*args: str, cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _ci_jobs():
    return (yaml.safe_load(CI_YML.read_text(encoding="utf-8")).get("jobs") or {})


def _job_runs(job: dict) -> str:
    return "\n".join(str(s.get("run") or "") for s in (job.get("steps") or []))


def _pin(name: str, text: str) -> str:
    key = name.lower().replace("_", "-")
    for line in text.splitlines():
        raw = line.split("#", 1)[0].strip()
        if not raw or "==" not in raw:
            continue
        pkg, ver = raw.split("==", 1)
        if pkg.lower().replace("_", "-") == key:
            return ver
    raise AssertionError(f"{name} pin missing")


def _requires(dist: str, prefix: str) -> list[str]:
    reqs = metadata.requires(dist) or []
    return [r for r in reqs if r.split(";")[0].strip().lower().startswith(prefix)]


# -- registry + notes ------------------------------------------------------


def test_registry_schema_forbids_bare_suppression():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert "Never a bare pip-audit --ignore-vuln" in " ".join(registry.get("rules") or [])
    for row in registry.get("adjudications") or []:
        date.fromisoformat(row["date"])
        assert row["decision"] != "suppress"
        note = REPO_ROOT / row["note"]
        assert note.is_file(), row["note"]
        text = note.read_text(encoding="utf-8")
        assert row["id"] in text
        assert row["date"] in text
        assert row["package"] in text


def test_readme_names_the_click_lesson():
    text = README.read_text(encoding="utf-8")
    assert "8.3.3" in text
    assert "gTTS 2.5.4" in text
    assert "click<8.2" in text
    assert "Requires-Dist" in text


def test_every_registry_row_has_a_dated_note_naming_the_id():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for row in registry.get("adjudications") or []:
        date.fromisoformat(row["date"])
        note = REPO_ROOT / row["note"]
        assert note.is_file(), row["note"]
        text = note.read_text(encoding="utf-8")
        assert row["id"] in text
        assert row["date"] in text
        assert "Decision:" in text or "decision" in text.lower()


# -- adjudicate against declared metadata, not a scanner summary -----------


def test_gtts_declares_click_below_eight_two():
    """The constraint is on gTTS, not a ceiling we invented."""
    click_reqs = _requires("gTTS", "click")
    assert click_reqs, "gTTS dropped its click pin — re-read Requires-Dist"
    joined = " ".join(click_reqs)
    assert "<8.2" in joined
    assert ">=7.1" in joined


def test_requirements_do_not_invent_a_click_ceiling():
    """A workplan that writes click<8.2 into the pin file is the miss."""
    text = REQ.read_text(encoding="utf-8")
    for line in text.splitlines():
        raw = line.split("#", 1)[0].strip().lower()
        if raw.startswith("click"):
            assert "<8.2" not in raw, f"invented click ceiling: {line}"


def test_click_pin_is_the_highest_the_declared_graph_allows():
    """Published fix is 8.3.3. Take it if gTTS (or a newer gTTS) allows it."""
    click_ver = Version(_pin("click", LOCK.read_text(encoding="utf-8")))
    gtts_click = " ".join(_requires("gTTS", "click"))
    if "<8.2" in gtts_click:
        assert click_ver < Version("8.2"), (
            f"lock has click {click_ver} but gTTS still declares {gtts_click}"
        )
    else:
        assert click_ver >= Version("8.3.3"), (
            f"gTTS no longer caps click<8.2 ({gtts_click}); "
            f"the real fix is 8.3.3, not a ceiling — lock has {click_ver}"
        )


def test_click_note_names_the_gtts_constraint_not_a_ceiling():
    note = (
        REPO_ROOT
        / "docs"
        / "security"
        / "dependency-adjudications"
        / "2026-09-11-click.md"
    ).read_text(encoding="utf-8")
    assert "PYSEC-2026-2132" in note
    assert "2026-09-11" in note
    assert "8.3.3" in note
    assert "gTTS 2.5.4" in note
    assert "click<8.2,>=7.1" in note
    assert "accept_constrained" in note
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["adjudications"]
    click = next(r for r in rows if r["id"] == "PYSEC-2026-2132")
    assert click["decision"] == "accept_constrained"
    assert click["evidence"]["kind"] == "declared_requires_dist"
    assert click["evidence"]["constraining_package"] == "gTTS"


def test_upgradeable_linux_pins_cleared_the_published_fixes():
    """Four of the five CI-named rows, plus python-dotenv, had fixes. Upgrade."""
    req = REQ.read_text(encoding="utf-8")
    lock = LOCK.read_text(encoding="utf-8")
    assert Version(_pin("cryptography", req)) >= Version("50.0.0")
    assert Version(_pin("cryptography", lock)) >= Version("50.0.0")
    assert Version(_pin("pypdf", req)) >= Version("6.16.1")
    assert Version(_pin("pypdf", lock)) >= Version("6.16.1")
    assert Version(_pin("mlflow", req)) >= Version("3.15.0")
    assert Version(_pin("mlflow", lock)) >= Version("3.15.0")
    assert Version(_pin("python-dotenv", req)) >= Version("1.2.2")
    assert Version(_pin("python-dotenv", lock)) >= Version("1.2.2")


def test_registry_lists_exactly_the_two_remaining_linux_ids():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["adjudications"]
    ids = sorted(r["id"] for r in rows)
    assert ids == ["PYSEC-2022-252", "PYSEC-2026-2132"]


def test_deep_translator_note_covers_the_unfixed_takeover():
    note = (
        REPO_ROOT
        / "docs"
        / "security"
        / "dependency-adjudications"
        / "2026-09-11-deep-translator.md"
    ).read_text(encoding="utf-8")
    assert "PYSEC-2022-252" in note
    assert "2026-09-11" in note
    assert "1.11.4" in note
    assert "accept_until_fix" in note
    assert _pin("deep-translator", REQ.read_text(encoding="utf-8")) == "1.11.4"


# -- script mutations (synthetic scanner JSON, no live feed) ---------------


def test_adjudicated_finding_with_empty_fix_exits_0(audit, tmp_path):
    pip = _write_json(
        tmp_path / "pip.json",
        {
            "dependencies": [
                {
                    "name": "deep-translator",
                    "version": "1.11.4",
                    "vulns": [
                        {
                            "id": "PYSEC-2022-252",
                            "fix_versions": [],
                            "aliases": [],
                        }
                    ],
                }
            ]
        },
    )
    proc = _run("--pip-json", str(pip))
    assert proc.returncode == 0, proc.stderr
    assert "ok:" in proc.stdout


def test_undocumented_finding_exits_1(audit, tmp_path):
    pip = _write_json(
        tmp_path / "pip.json",
        {
            "dependencies": [
                {
                    "name": "demo",
                    "version": "1.0.0",
                    "vulns": [{"id": "PYSEC-2099-1", "fix_versions": ["1.0.1"], "aliases": []}],
                }
            ]
        },
    )
    proc = _run("--pip-json", str(pip))
    assert proc.returncode == 1, proc.stderr
    assert "undocumented" in proc.stderr
    assert "PYSEC-2099-1" in proc.stderr
    assert "--ignore-vuln" in proc.stderr


def test_accept_constrained_with_a_published_fix_is_not_stale(audit, tmp_path):
    """gTTS's Requires-Dist is why click stays below 8.3.3. That is not a ceiling."""
    note_dir = tmp_path / "docs" / "security" / "dependency-adjudications"
    note_dir.mkdir(parents=True)
    (note_dir / "click.md").write_text(
        "PYSEC-2026-2132\n2026-09-11\nDecision: accept_constrained\nclick\n",
        encoding="utf-8",
    )
    registry = {
        "adjudications": [
            {
                "id": "PYSEC-2026-2132",
                "aliases": ["CVE-2026-7246"],
                "package": "click",
                "date": "2026-09-11",
                "note": "docs/security/dependency-adjudications/click.md",
                "decision": "accept_constrained",
                "evidence": {
                    "kind": "declared_requires_dist",
                    "constraining_package": "gTTS",
                    "constraint": "click<8.2,>=7.1",
                },
            }
        ]
    }
    reg = _write_json(tmp_path / "registry.json", registry)
    pip = _write_json(
        tmp_path / "pip.json",
        {
            "dependencies": [
                {
                    "name": "click",
                    "version": "8.1.8",
                    "vulns": [
                        {
                            "id": "PYSEC-2026-2132",
                            "fix_versions": ["8.3.3"],
                            "aliases": ["CVE-2026-7246"],
                        }
                    ],
                }
            ]
        },
    )
    proc = _run(
        "--pip-json",
        str(pip),
        "--registry",
        str(reg),
        "--repo",
        str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok:" in proc.stdout


def test_evaluate_rejects_a_suppress_decision(audit):
    registry = {
        "adjudications": [
            {
                "id": "PYSEC-2099-3",
                "aliases": [],
                "package": "demo",
                "date": "2026-09-11",
                "note": "docs/security/dependency-adjudications/README.md",
                "decision": "suppress",
            }
        ]
    }
    errors = audit.evaluate([], registry, repo=REPO_ROOT)
    assert any("bare suppression" in e for e in errors)


def test_stale_adjudication_when_a_fix_appears_exits_1(audit, tmp_path):
    """A dated note is not a forever ignore. A published fix must ship."""
    registry = {
        "schema": "store.dep_adjudication.v1",
        "adjudications": [
            {
                "id": "PYSEC-2099-4",
                "aliases": [],
                "package": "demo",
                "date": "2026-09-11",
                "note": "docs/security/dependency-adjudications/README.md",
                "decision": "accept_until_fix",
            }
        ]
    }
    reg = _write_json(tmp_path / "registry.json", registry)
    # Give the planted note the id so _note_ok passes.
    note = tmp_path / "docs" / "security" / "dependency-adjudications"
    note.mkdir(parents=True)
    (note / "README.md").write_text(
        "PYSEC-2099-4\n2026-09-11\nDecision: accept_until_fix\n",
        encoding="utf-8",
    )
    pip = _write_json(
        tmp_path / "pip.json",
        {
            "dependencies": [
                {
                    "name": "demo",
                    "version": "1.0.0",
                    "vulns": [
                        {
                            "id": "PYSEC-2099-4",
                            "fix_versions": ["1.0.1"],
                            "aliases": [],
                        }
                    ],
                }
            ]
        },
    )
    proc = _run(
        "--pip-json",
        str(pip),
        "--registry",
        str(reg),
        "--repo",
        str(tmp_path),
    )
    assert proc.returncode == 1, proc.stdout
    assert "stale adjudication" in proc.stderr
    assert "1.0.1" in proc.stderr


def test_duplicate_pip_audit_rows_collapse_to_one(audit):
    findings = audit.findings_from_pip_audit(
        {
            "dependencies": [
                {
                    "name": "demo",
                    "version": "1.0.0",
                    "vulns": [
                        {"id": "PYSEC-2099-5", "fix_versions": [], "aliases": []},
                        {"id": "PYSEC-2099-5", "fix_versions": [], "aliases": []},
                    ],
                }
            ]
        }
    )
    assert len(findings) == 1
    assert findings[0].vuln_id == "PYSEC-2099-5"


def test_wrapper_audits_requirements_txt_not_the_runner_env(audit):
    """GHA's setuptools is not a store pin.

    Mutation killed: dropping ``-r requirements.txt`` and scanning the
    local env, then papering over the extra finding with --ignore-vuln.
    """
    argv = audit.pip_audit_argv(REQ)
    joined = " ".join(argv)
    assert "-r" in argv
    assert str(REQ) in argv
    assert "--ignore-vuln" not in joined
    for line in REQ.read_text(encoding="utf-8").splitlines():
        raw = line.split("#", 1)[0].strip().lower()
        assert not raw.startswith("setuptools")


# -- CI wiring -------------------------------------------------------------


def test_ci_has_fail_closed_python_audit():
    jobs = _ci_jobs()
    assert "full-suite" in jobs
    job = jobs["full-suite"]
    assert job.get("continue-on-error") in (None, False)
    assert job.get("runs-on") == "ubuntu-latest"
    runs = _job_runs(job)
    assert "dep_audit.py" in runs
    assert "--ignore-vuln" not in runs
    for step in job.get("steps") or []:
        if "dep_audit" in str(step.get("run") or "") or "pip_audit" in str(step.get("run") or ""):
            assert step.get("continue-on-error") in (None, False), step


def test_workflows_have_no_bare_ignore(audit):
    hits = audit.workflow_has_bare_ignore(CI_YML.read_text(encoding="utf-8"))
    assert hits == [], hits
