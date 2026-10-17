"""Hermetic coverage for the construction-kit publisher.

The GitHub workflow that clones The_Fork is not a test: it only fires on
manual dispatch or a push that touches the construction manifest, and a
cross-repo checkout failure looks like a publisher bug. These tests run the
script against a tiny in-tree Fork fixture — no network, no second repo —
so a break is caught on every PR.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish_construction_kit.py"
_spec = importlib.util.spec_from_file_location("publish_construction_kit", _SCRIPT)
publisher = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(publisher)

_REAL_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "block_store"
    / "kits"
    / "construction"
    / "manifest.json"
)

# A slice of the real kit shape: container, domain block, prompt, data, CLI.
_FIXTURE_FILES = {
    "app/containers/construction.py": "class ConstructionContainer:\n    version = 'fixture'\n",
    "app/blocks/construction_v2.py": "class ConstructionV2:\n    pass\n",
    "app/prompts/construction_expert.txt": "You are the construction expert.\n",
    "app/knowledge/construction_kb.json": '{"domains": ["bim"]}\n',
    "cli/cerebrum_cli/__init__.py": "__version__ = '0'\n",
}

_FIXTURE_BLOCKS = ["construction_v2", "pdf"]


def _manifest(artifacts=None, **extra) -> dict:
    items = artifacts if artifacts is not None else [
        {"src": rel, "dest": rel} for rel in _FIXTURE_FILES
    ]
    body = {
        "id": "construction",
        "blocks": extra.pop("blocks", _FIXTURE_BLOCKS),
        "artifacts": items,
    }
    body.update(extra)
    return body


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_tree(root: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return root


def _fork_and_kit(tmp_path: Path, files: dict[str, str] | None = None):
    fork = _write_tree(tmp_path / "The_Fork", files if files is not None else _FIXTURE_FILES)
    manifest = _write_json(
        tmp_path / "block_store" / "kits" / "construction" / "manifest.json",
        _manifest(),
    )
    bundle = tmp_path / "block_store" / "kits" / "construction" / "bundle"
    return fork, manifest, bundle


# -- happy path ------------------------------------------------------------


def test_publish_copies_the_fixture_tree_into_the_bundle(tmp_path):
    fork, manifest, bundle = _fork_and_kit(tmp_path)

    code = publisher.publish(fork, manifest_path=manifest, bundle_dir=bundle)

    assert code == 0
    for rel, content in _FIXTURE_FILES.items():
        copied = bundle / rel
        assert copied.is_file(), f"missing from bundle: {rel}"
        assert copied.read_text(encoding="utf-8") == content


def test_publish_reports_bundle_ready_and_registered_blocks(tmp_path, capsys):
    fork, manifest, bundle = _fork_and_kit(tmp_path)

    assert publisher.publish(fork, manifest_path=manifest, bundle_dir=bundle) == 0

    out = capsys.readouterr().out
    assert "Copied 5/5 artifacts" in out
    assert "bundle_ready=True" in out
    assert "blocks_registered=2" in out


def test_main_accepts_fixture_paths_and_does_not_touch_the_store(tmp_path):
    """CLI path the workflow uses, pointed at a fixture instead of The_Fork."""
    fork, manifest, bundle = _fork_and_kit(tmp_path)
    store_bundle = (
        Path(__file__).resolve().parents[1]
        / "block_store"
        / "kits"
        / "construction"
        / "bundle"
        / "app"
        / "containers"
        / "construction.py"
    )
    before = store_bundle.stat().st_mtime_ns if store_bundle.exists() else None

    code = publisher.main(
        [
            "--fork-root",
            str(fork),
            "--manifest",
            str(manifest),
            "--bundle-dir",
            str(bundle),
        ]
    )

    assert code == 0
    assert (bundle / "app" / "containers" / "construction.py").is_file()
    if before is not None:
        assert store_bundle.stat().st_mtime_ns == before


# -- refusals --------------------------------------------------------------


def test_missing_fork_root_is_a_clear_error(tmp_path, capsys):
    missing = tmp_path / "no-such-fork"
    manifest = _write_json(tmp_path / "manifest.json", _manifest())

    code = publisher.publish(
        missing, manifest_path=manifest, bundle_dir=tmp_path / "bundle"
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "Fork root not found" in err
    assert str(missing.resolve()) in err
    assert "bopoadz-del/The_Fork" in err
    assert "Traceback" not in err


def test_a_file_is_not_a_fork_root(tmp_path, capsys):
    not_a_dir = tmp_path / "The_Fork"
    not_a_dir.write_text("not a tree\n", encoding="utf-8")
    manifest = _write_json(tmp_path / "manifest.json", _manifest())

    code = publisher.publish(
        not_a_dir, manifest_path=manifest, bundle_dir=tmp_path / "bundle"
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "not a directory" in err
    assert "bopoadz-del/The_Fork" in err
    assert "Traceback" not in err


def test_empty_directory_is_not_a_fork_tree(tmp_path, capsys):
    """A path that exists but has no app/ is malformed, not 'missing artifacts'."""
    empty = tmp_path / "empty-clone"
    empty.mkdir()
    manifest = _write_json(tmp_path / "manifest.json", _manifest())

    code = publisher.publish(
        empty, manifest_path=manifest, bundle_dir=tmp_path / "bundle"
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "not a The_Fork tree" in err
    assert str(empty / "app") in err
    assert "Traceback" not in err


def test_incomplete_fork_lists_every_missing_path(tmp_path, capsys):
    fork, manifest, bundle = _fork_and_kit(
        tmp_path,
        files={"app/containers/construction.py": "class ConstructionContainer:\n    pass\n"},
    )

    code = publisher.publish(fork, manifest_path=manifest, bundle_dir=bundle)

    assert code == 1
    err = capsys.readouterr().err
    assert "missing declared artifacts" in err
    assert "app/blocks/construction_v2.py" in err
    assert "app/prompts/construction_expert.txt" in err
    assert "app/knowledge/construction_kb.json" in err
    assert "cli/cerebrum_cli/__init__.py" in err
    assert "Traceback" not in err
    assert not (bundle / "app" / "blocks" / "construction_v2.py").exists()
    # What *was* present is still copied; the failure is the incomplete set.
    assert (bundle / "app" / "containers" / "construction.py").is_file()


def test_refresh_keeps_bundle_orphans_when_fork_dropped_them(tmp_path, capsys):
    """Fork drift: paths declared in the manifest but gone from Fork live on in bundle/."""
    fork = _write_tree(
        tmp_path / "The_Fork",
        {"app/containers/construction.py": "class ConstructionContainer:\n    pass\n"},
    )
    manifest = _write_json(
        tmp_path / "manifest.json",
        _manifest(
            artifacts=[
                {"src": "app/containers/construction.py", "dest": "app/containers/construction.py"},
                {"src": "app/blocks/construction_v2.py", "dest": "app/blocks/construction_v2.py"},
            ]
        ),
    )
    bundle = tmp_path / "bundle"
    orphan = bundle / "app" / "blocks" / "construction_v2.py"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("# bundle-only orphan\n", encoding="utf-8")

    code = publisher.publish(
        fork, manifest_path=manifest, bundle_dir=bundle, refresh=True
    )

    assert code == 0
    err = capsys.readouterr().err
    assert "Retained 1 artifact(s) from bundle/" in err
    assert "app/blocks/construction_v2.py" in err
    assert orphan.read_text(encoding="utf-8") == "# bundle-only orphan\n"
    assert (bundle / "app" / "containers" / "construction.py").is_file()


def test_malformed_manifest_json_is_a_clear_error(tmp_path, capsys):
    fork = _write_tree(tmp_path / "The_Fork", _FIXTURE_FILES)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{not json", encoding="utf-8")

    code = publisher.publish(
        fork, manifest_path=manifest, bundle_dir=tmp_path / "bundle"
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "not valid JSON" in err
    assert str(manifest) in err
    assert "Traceback" not in err


@pytest.mark.parametrize(
    "payload,needle",
    [
        (["not", "an", "object"], "must be a JSON object"),
        ({"id": "construction", "artifacts": "oops"}, "must be a list"),
        ({"id": "construction", "artifacts": []}, "No artifacts listed"),
        (
            {"id": "construction", "artifacts": [{"dest": "x.py"}]},
            "malformed",
        ),
    ],
)
def test_malformed_manifest_shape_is_a_clear_error(tmp_path, capsys, payload, needle):
    fork = _write_tree(tmp_path / "The_Fork", _FIXTURE_FILES)
    manifest = _write_json(tmp_path / "manifest.json", payload)

    code = publisher.publish(
        fork, manifest_path=manifest, bundle_dir=tmp_path / "bundle"
    )

    assert code == 1
    err = capsys.readouterr().err
    assert needle in err
    assert "Traceback" not in err


def test_the_checked_in_manifest_loads_without_error():
    """The store manifest the workflow reads must itself be well-formed."""
    artifacts, error = publisher.load_artifacts(_REAL_MANIFEST)
    assert error is None, error
    assert artifacts
    # The declared container's source -- a module or a package -- is shipped.
    import json
    module = json.loads(_REAL_MANIFEST.read_text(encoding="utf-8"))["container"]["class"].rsplit(".", 1)[0]
    base = module.replace(".", "/")
    assert f"{base}.py" in artifacts or f"{base}/__init__.py" in artifacts
    assert all(isinstance(src, str) and src for src in artifacts)
