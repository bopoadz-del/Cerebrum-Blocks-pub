"""Served-text follow-up to #16: run the served-text detector over the text the
blocks actually serve, found from the registry structure (no file list).

A block's served text is
  * every human-facing string (description / check / label) anywhere in its
    ``<registry>/<block>/block.json`` manifest, and
  * the contents of any file a manifest input names as its default when the
    input's name ends in ``_file`` (e.g. a skill file), resolved against the
    project root the registry lives in.
The detector is imported from #16, not copied.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.blocks import _REGISTRY_ROOT
from tests.test_served_text_detector import served_text_hits

SERVED_FIELDS = ("description", "check", "label")
FILE_INPUT_SUFFIX = "_file"


def _manifest_strings(node, where):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in SERVED_FIELDS and isinstance(value, str):
                yield f"{where}/{key}", value
            else:
                yield from _manifest_strings(value, f"{where}/{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _manifest_strings(value, f"{where}[{i}]")


def served_texts(registry: Path, project_root: Path):
    """(source, text) for every text a block in ``registry`` serves."""
    for manifest_path in sorted(registry.glob("*/block.json")):
        block = manifest_path.parent.name
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        yield from _manifest_strings(manifest, block)
        for item in manifest.get("inputs", []) or []:
            name, default = item.get("name", ""), item.get("default")
            if str(name).endswith(FILE_INPUT_SUFFIX) and isinstance(default, str):
                path = project_root / default
                if path.is_file():
                    yield f"{block}:{default}", path.read_text(encoding="utf-8")


def served_text_findings(registry: Path, project_root: Path) -> list:
    return [(src, kind, match)
            for src, text in served_texts(registry, project_root)
            for _line, kind, match in served_text_hits(text)]


# ---------------------------------------------------------------- fixtures

def _findings(registry, project_root):
    """Findings, or the raised exception, so a broken rule fails as an assert."""
    try:
        return served_text_findings(registry, project_root)
    except Exception as exc:  # noqa: BLE001
        return exc

def _project(tmp_path, manifests: dict, files: dict = None) -> Path:
    reg = tmp_path / "block_registry"
    for block, manifest in manifests.items():
        (reg / block).mkdir(parents=True)
        (reg / block / "block.json").write_text(json.dumps(manifest), encoding="utf-8")
    for rel, text in (files or {}).items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return reg


def test_two_projects_give_two_results(tmp_path):
    a = _project(tmp_path / "a", {"alpha": {"description": "Deploy on Heroku"}})
    b = _project(tmp_path / "b", {"beta": {"description": "set <x> on aws"}})
    assert _findings(a, tmp_path / "a") == [("alpha/description", "provider", "Heroku")]
    assert _findings(b, tmp_path / "b") == [
        ("beta/description", "provider", "aws"), ("beta/description", "placeholder", "<x>")]


def test_clean_project_has_no_findings(tmp_path):
    reg = _project(tmp_path, {"alpha": {"description": "a neutral block"}})
    assert _findings(reg, tmp_path) == []


@pytest.mark.parametrize("field", ["description", "check", "label"])
def test_each_served_field_is_scanned_when_nested(tmp_path, field):
    reg = _project(tmp_path, {"alpha": {"acceptance": [{field: "on Azure"}]}})
    assert _findings(reg, tmp_path) == [(f"alpha/acceptance[0]/{field}", "provider", "Azure")]


@pytest.mark.parametrize("field", ["name", "id", "image", "author"])
def test_non_served_fields_are_not_scanned(tmp_path, field):
    reg = _project(tmp_path, {"alpha": {field: "ghcr <x> aws", "description": "ok"}})
    assert _findings(reg, tmp_path) == []


def test_file_input_default_is_read_from_project_root(tmp_path):
    reg = _project(tmp_path,
                   {"alpha": {"inputs": [{"name": "guide_file", "default": "data/g.md"}]}},
                   {"data/g.md": "fine\nclone <repo-url>\n"})
    assert _findings(reg, tmp_path) == [("alpha:data/g.md", "placeholder", "<repo-url>")]


@pytest.mark.parametrize("item", [
    {"name": "guide_path", "default": "data/g.md"},      # name not ending in _file
    {"name": "guide_file", "default": ["data/g.md"]},    # non-string default
    {"name": "guide_file", "default": "data/missing.md"},  # absent file
])
def test_file_input_rule_boundaries(tmp_path, item):
    reg = _project(tmp_path, {"alpha": {"inputs": [item]}}, {"data/g.md": "on render\n"})
    assert _findings(reg, tmp_path) == []


@pytest.mark.parametrize("description, expected", [
    ("", [("alpha/description", "empty", "")]),
    ("  \t", [("alpha/description", "empty", "")]),
    ("TODO", [("alpha/description", "todo", "TODO")]),
    ("lorem ipsum", [("alpha/description", "lorem", "lorem ipsum")]),
    ("Scores a todolist", []),
])
def test_new_rules_reach_block_descriptions(tmp_path, description, expected):
    reg = _project(tmp_path, {"alpha": {"description": description}})
    assert _findings(reg, tmp_path) == expected


def test_served_field_holding_an_object_is_walked(tmp_path):
    reg = _project(tmp_path, {"alpha": {"label": {"description": "on aws"}}})
    assert _findings(reg, tmp_path) == [("alpha/label/description", "provider", "aws")]


def test_every_block_in_registry_is_scanned(tmp_path):
    reg = _project(tmp_path, {"a1": {"description": "aws"}, "b2": {"label": "vercel"}})
    assert _findings(reg, tmp_path) == [
        ("a1/description", "provider", "aws"), ("b2/label", "provider", "vercel")]


def test_real_registry_is_discovered():
    try:
        texts = list(served_texts(_REGISTRY_ROOT, _REGISTRY_ROOT.parent))
    except Exception as exc:  # noqa: BLE001
        texts = [(repr(exc), "")]
    assert len({src.split("/")[0].split(":")[0] for src, _ in texts}) == \
        len(list(_REGISTRY_ROOT.glob("*/block.json")))


def test_real_served_text_is_provider_neutral_and_placeholder_free():
    # No baseline, no allowlist: real hits are reported, not hidden.
    assert served_text_findings(_REGISTRY_ROOT, _REGISTRY_ROOT.parent) == []


# ---- CI pin (G6 H2): this file must run in a blocking Backend step ----
CI_STEP = "Served-text scan over block registry (ST-7d)"
CI_FILES = {"tests/test_served_text_blocks.py", "tests/test_served_text_detector.py"}


def test_ci_backend_runs_served_text_scan_in_blocking_step():
    import yaml

    from tests.test_ci_named_followup_steps import WORKFLOW, blocking_named_steps

    steps = blocking_named_steps(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")), "backend")
    assert CI_STEP in steps, f"no blocking, run-after-failure Backend step named {CI_STEP!r}"
    missing = CI_FILES - steps[CI_STEP]
    assert not missing, f"step {CI_STEP!r} does not run {sorted(missing)}"
