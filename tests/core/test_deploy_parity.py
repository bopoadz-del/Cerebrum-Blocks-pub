"""Dockerfile / render.yaml parity: one service, one runtime contract.

The Docker image and the Render native runtime must install the same system
packages, start the same server, and pin the same Python line — drift between
them means the two deploy paths run different platforms.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# System packages the blocks actually need at runtime.
RUNTIME_APT_PACKAGES = {"tesseract-ocr", "tesseract-ocr-ara", "poppler-utils", "libgl1", "libglib2.0-0"}


def _dockerfile_packages() -> set:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    return {p for p in RUNTIME_APT_PACKAGES if re.search(rf"\b{re.escape(p)}\b", text)}


def _render_build_packages() -> set:
    text = (ROOT / "render-build.sh").read_text(encoding="utf-8")
    return {p for p in RUNTIME_APT_PACKAGES if re.search(rf"\b{re.escape(p)}\b", text)}


def test_runtime_apt_packages_match_across_deploy_paths():
    docker = _dockerfile_packages()
    render = _render_build_packages()
    assert docker == RUNTIME_APT_PACKAGES, f"Dockerfile missing: {RUNTIME_APT_PACKAGES - docker}"
    assert render == RUNTIME_APT_PACKAGES, f"render-build.sh missing: {RUNTIME_APT_PACKAGES - render}"


def test_start_commands_agree():
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    procfile = (ROOT / "Procfile").read_text(encoding="utf-8")
    for text, name in ((render, "render.yaml"), (entry, "entrypoint.sh"), (procfile, "Procfile")):
        assert "uvicorn app.main:app" in text, f"{name} does not start the API server"
        assert "--no-access-log" in text, f"{name} start flags drifted (--no-access-log)"


def test_python_version_pins_agree():
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    runtime = (ROOT / "runtime.txt").read_text(encoding="utf-8").strip()
    render_version = re.search(r"PYTHON_VERSION\s*\n\s*value:\s*([\d.]+)", render)
    assert render_version, "render.yaml missing PYTHON_VERSION"
    assert runtime == f"python-{render_version.group(1)}", (
        f"runtime.txt ({runtime}) disagrees with render.yaml ({render_version.group(1)})"
    )
