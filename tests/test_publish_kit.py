"""The publisher's three load-bearing behaviours.

Publishing is the step that decides whether a kit the store advertises can
actually be installed. Each test below pins a way that step used to be able
to fail quietly.
"""

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish_kit.py"
_spec = importlib.util.spec_from_file_location("publish_kit", _SCRIPT)
publish_kit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(publish_kit)


# -- directories are artifacts too -----------------------------------------


def test_a_directory_artifact_is_copied_not_crashed_on(tmp_path):
    """``shutil.copy2`` raises IsADirectoryError on a directory.

    Three of automotive's artifacts are directories (``schemas/``,
    ``prompts/``, and the declared-but-unwritten ``evaluation/``). A publisher
    that assumes every artifact is a file cannot publish a RAG kit at all.
    """
    src = tmp_path / "schemas"
    src.mkdir()
    (src / "recall.json").write_text('{"title": "AutomotiveRecall"}', encoding="utf-8")
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "junk.pyc").write_text("x", encoding="utf-8")

    dest = tmp_path / "bundle" / "schemas"
    publish_kit.copy_artifact(src, dest)

    assert (dest / "recall.json").is_file()
    assert not (dest / "__pycache__").exists(), "build droppings were published"


def test_recopying_a_directory_does_not_accumulate_stale_files(tmp_path):
    """A republish must leave the bundle equal to the source, not a union.

    Without this, a schema deleted at the kit root lives on in the bundle and
    ships to clients forever.
    """
    src = tmp_path / "schemas"
    src.mkdir()
    (src / "keep.json").write_text("{}", encoding="utf-8")
    (src / "retired.json").write_text("{}", encoding="utf-8")
    dest = tmp_path / "bundle" / "schemas"
    publish_kit.copy_artifact(src, dest)
    assert (dest / "retired.json").exists()

    (src / "retired.json").unlink()
    publish_kit.copy_artifact(src, dest)

    assert (dest / "keep.json").exists()
    assert not (dest / "retired.json").exists(), "bundle kept a file the kit dropped"


# -- where an artifact is authored -----------------------------------------


def test_kit_authored_content_wins_over_the_repo_copy(tmp_path):
    """Kit root beats repo root, so a kit can carry its own copy of a file."""
    kit_dir = tmp_path / "kits" / "automotive"
    (kit_dir).mkdir(parents=True)
    (kit_dir / "sandbox.py").write_text("# the kit's own", encoding="utf-8")

    original_root = publish_kit.PROJECT_ROOT
    try:
        publish_kit.PROJECT_ROOT = tmp_path / "repo"
        (publish_kit.PROJECT_ROOT).mkdir()
        (publish_kit.PROJECT_ROOT / "sandbox.py").write_text("# shared", encoding="utf-8")

        found = publish_kit.resolve_source(kit_dir, "sandbox.py")
        assert found == kit_dir / "sandbox.py"

        # and the repo copy is still reachable when the kit has none
        assert publish_kit.resolve_source(kit_dir, "other.py") is None
    finally:
        publish_kit.PROJECT_ROOT = original_root


# -- the refusal -----------------------------------------------------------


def test_declared_but_absent_is_reported(tmp_path):
    """The automotive class, stated as data.

    ``install_kit`` raises ContainerKitError on exactly this condition. The
    publisher checks it too, so the failure lands on the person publishing
    rather than on whoever installs next.
    """
    bundle = tmp_path / "bundle"
    (bundle / "schemas").mkdir(parents=True)
    artifacts = [
        {"src": "schemas/", "dest": "schemas/"},
        {"src": "evaluation/", "dest": "evaluation/"},
    ]
    assert publish_kit.missing_from_bundle(bundle, artifacts) == ["evaluation/"]


def test_a_complete_bundle_reports_nothing_missing(tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "schemas").mkdir(parents=True)
    (bundle / "source_manifest.json").write_text("{}", encoding="utf-8")
    artifacts = [
        {"src": "schemas/", "dest": "schemas/"},
        {"src": "source_manifest.json", "dest": "source_manifest.json"},
    ]
    assert publish_kit.missing_from_bundle(bundle, artifacts) == []


def test_scaffold_refuses_to_overwrite_an_authored_manifest(tmp_path, capsys):
    """The regression that would have silently un-done #64.

    The template emits a fixed 14-artifact list. automotive's authored
    manifest carries 18. Regenerating over it drops the four that make it a
    RAG kit, and nothing in the output would have said so.
    """
    kit_dir = tmp_path / "automotive"
    kit_dir.mkdir()
    manifest_path = kit_dir / "manifest.json"
    authored = {"id": "automotive", "artifacts": [{"src": "schemas/", "dest": "schemas/"}]}
    manifest_path.write_text(json.dumps(authored), encoding="utf-8")

    code = publish_kit.scaffold(
        kit_dir, manifest_path, "automotive", dry_run=False, regenerate=False
    )

    assert code == 1
    assert "Refusing to overwrite" in capsys.readouterr().err
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == authored


def test_mirror_refuses_when_an_artifact_is_authored_nowhere(tmp_path, capsys):
    """Declaring a path nobody wrote is the root cause, not the symptom."""
    kit_dir = tmp_path / "automotive"
    kit_dir.mkdir()
    manifest_path = kit_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"id": "automotive", "artifacts": [{"src": "evaluation/", "dest": "evaluation/"}]}
        ),
        encoding="utf-8",
    )

    code = publish_kit.mirror(kit_dir, manifest_path, dry_run=False, check_only=False)

    assert code == 1
    assert "authored nowhere" in capsys.readouterr().err


def test_mirror_publishes_and_then_verifies(tmp_path, monkeypatch):
    """The happy path still ends in a completeness check, not a hope.

    The composition audit is stubbed here because it inspects the real
    ``block_store/kits`` tree; a demo kit in tmp_path is not registered there
    and the audit would report on the wrong thing. That mirror *calls* the
    audit is pinned separately below.
    """
    monkeypatch.setattr(publish_kit, "composition_audit", lambda *a, **k: 0)
    kit_dir = tmp_path / "demo"
    (kit_dir / "schemas").mkdir(parents=True)
    (kit_dir / "schemas" / "a.json").write_text("{}", encoding="utf-8")
    (kit_dir / "source_manifest.json").write_text("{}", encoding="utf-8")
    manifest_path = kit_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "id": "demo",
                "artifacts": [
                    {"src": "schemas/", "dest": "schemas/"},
                    {"src": "source_manifest.json", "dest": "source_manifest.json"},
                ],
            }
        ),
        encoding="utf-8",
    )

    code = publish_kit.mirror(kit_dir, manifest_path, dry_run=False, check_only=False)

    assert code == 0
    assert (kit_dir / "bundle" / "schemas" / "a.json").is_file()
    assert (kit_dir / "bundle" / "source_manifest.json").is_file()


@pytest.mark.parametrize("check_only", [True, False])
def test_a_kit_with_no_artifacts_is_not_an_error(tmp_path, check_only):
    """universal_kernel declares none. That is a state, not a failure."""
    kit_dir = tmp_path / "universal_kernel"
    kit_dir.mkdir()
    manifest_path = kit_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"id": "universal_kernel"}), encoding="utf-8")

    assert publish_kit.mirror(kit_dir, manifest_path, False, check_only) == 0


def test_mirror_runs_the_composition_audit(tmp_path, monkeypatch):
    """#69's publish gate must be on the DEFAULT path.

    After #69 and #74 merged, the audit call sat inside ``scaffold()`` only.
    ``mirror`` is the default and the mode every already-authored kit takes,
    so the gate had quietly stopped guarding anything that actually ships.
    """
    kit_dir = tmp_path / "demo"
    kit_dir.mkdir()
    (kit_dir / "source_manifest.json").write_text("{}", encoding="utf-8")
    manifest_path = kit_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "id": "demo",
                "artifacts": [
                    {"src": "source_manifest.json", "dest": "source_manifest.json"}
                ],
            }
        ),
        encoding="utf-8",
    )

    calls = []
    monkeypatch.setattr(
        publish_kit, "composition_audit", lambda d, k: calls.append(d) or 0
    )
    assert publish_kit.mirror(kit_dir, manifest_path, False, False) == 0
    assert calls == ["demo"], "mirror published without running the composition audit"


def test_the_audit_verdict_decides_the_exit_code(tmp_path, monkeypatch):
    """A clean copy with a failing audit must not report success."""
    kit_dir = tmp_path / "demo"
    kit_dir.mkdir()
    (kit_dir / "source_manifest.json").write_text("{}", encoding="utf-8")
    manifest_path = kit_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "id": "demo",
                "artifacts": [
                    {"src": "source_manifest.json", "dest": "source_manifest.json"}
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(publish_kit, "composition_audit", lambda *a, **k: 1)
    assert publish_kit.mirror(kit_dir, manifest_path, False, False) == 1


def test_refresh_copies_what_it_can_and_still_fails(tmp_path, monkeypatch):
    """construction/insurance: sources partly gone, bundle is the only copy.

    Refresh must bring their shared platform code up to date -- otherwise a
    kit whose sources vanished is frozen on an old formula executor forever --
    while still exiting non-zero so nobody reads it as a complete publish.
    """
    kit_dir = tmp_path / "demo"
    kit_dir.mkdir()
    (kit_dir / "present.json").write_text('{"v": 2}', encoding="utf-8")
    manifest_path = kit_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "id": "demo",
                "artifacts": [
                    {"src": "present.json", "dest": "present.json"},
                    {"src": "vanished.json", "dest": "vanished.json"},
                ],
            }
        ),
        encoding="utf-8",
    )
    # A stale bundled copy of the orphan, as construction/insurance have.
    bundle = kit_dir / "bundle"
    bundle.mkdir()
    (bundle / "vanished.json").write_text('{"old": true}', encoding="utf-8")

    monkeypatch.setattr(publish_kit, "composition_audit", lambda *a, **k: 0)
    code = publish_kit.mirror(kit_dir, manifest_path, False, False, refresh=True)

    assert code == 1, "a partial publish must not report success"
    assert (bundle / "present.json").read_text(encoding="utf-8") == '{"v": 2}'
    assert (bundle / "vanished.json").exists(), "refresh destroyed the only copy"


def test_without_refresh_an_unreachable_source_writes_nothing(tmp_path):
    """Strict mirror refuses BEFORE copying -- no partial writes by default."""
    kit_dir = tmp_path / "demo"
    kit_dir.mkdir()
    (kit_dir / "present.json").write_text("{}", encoding="utf-8")
    manifest_path = kit_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "id": "demo",
                "artifacts": [
                    {"src": "present.json", "dest": "present.json"},
                    {"src": "vanished.json", "dest": "vanished.json"},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert publish_kit.mirror(kit_dir, manifest_path, False, False) == 1
    assert not (kit_dir / "bundle").exists(), "strict mirror wrote a partial bundle"
