"""Kit provenance must be verified on the live install path (fail closed)."""

import json
from pathlib import Path

import pytest

from app.core import container_kit_store as store
from block_store.kits.universal_kernel.wave1.provenance_verification import (
    build_provenance,
)


def _make_kit(root: Path, kit_id: str = "demo") -> Path:
    kit_dir = root / kit_id
    bundle = kit_dir / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (kit_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": kit_id,
                "name": "Demo",
                "version": "1.0.0",
                "status": "available",
                "artifacts": [{"src": "module.py", "dest": "app/generated/demo_module.py"}],
            }
        ),
        encoding="utf-8",
    )
    return kit_dir


@pytest.fixture
def kit_env(tmp_path, monkeypatch):
    kits_root = tmp_path / "kits"
    kits_root.mkdir()
    monkeypatch.setattr(store, "KITS_DIR", kits_root)
    monkeypatch.setattr(store, "INSTALL_STATE_PATH", tmp_path / "state.json")
    target = tmp_path / "target"
    target.mkdir()
    return kits_root, target


def test_install_refuses_tampered_kit(kit_env):
    kits_root, target = kit_env
    kit_dir = _make_kit(kits_root)
    build_provenance(kit_dir)
    # Tamper after the provenance manifest was signed.
    (kit_dir / "bundle" / "module.py").write_text("VALUE = 666\n", encoding="utf-8")

    with pytest.raises(store.ContainerKitError) as exc:
        store.install_kit("demo", target_root=target, force=True)
    assert "provenance" in str(exc.value).lower()


def test_install_verifies_intact_kit(kit_env):
    kits_root, target = kit_env
    kit_dir = _make_kit(kits_root)
    build_provenance(kit_dir)

    result = store.install_kit("demo", target_root=target, force=True)
    assert result["provenance"] == "verified"


def test_install_labels_missing_provenance(kit_env):
    kits_root, target = kit_env
    _make_kit(kits_root)

    result = store.install_kit("demo", target_root=target, force=True)
    assert result["provenance"] == "absent — unverified"
