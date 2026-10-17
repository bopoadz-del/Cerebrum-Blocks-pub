"""Tests for the neutral provenance verification sub-kit."""

import json

import pytest

from block_store.kits.universal_kernel.wave1.provenance_verification import (
    ProvenanceMismatch,
    build_provenance,
    sha256_of_file,
    verify_kit,
)


def test_build_provenance_and_verify(tmp_path):
    (tmp_path / "code.py").write_text("print('neutral')", encoding="utf-8")
    (tmp_path / "data.json").write_text('{"key": "value"}', encoding="utf-8")
    manifest = build_provenance(tmp_path)
    assert manifest["algorithm"] == "sha256"
    assert "code.py" in manifest["files"]
    assert verify_kit(tmp_path / "provenance.json") is True


def test_missing_file_raises_provenance_mismatch(tmp_path):
    (tmp_path / "code.py").write_text("print('neutral')", encoding="utf-8")
    (tmp_path / "data.json").write_text('{"key": "value"}', encoding="utf-8")
    build_provenance(tmp_path)
    (tmp_path / "data.json").unlink()
    with pytest.raises(ProvenanceMismatch, match="missing file"):
        verify_kit(tmp_path / "provenance.json")


def test_digest_mismatch_raises_provenance_mismatch(tmp_path):
    (tmp_path / "code.py").write_text("print('neutral')", encoding="utf-8")
    build_provenance(tmp_path)
    (tmp_path / "code.py").write_text("print('tampered')", encoding="utf-8")
    with pytest.raises(ProvenanceMismatch, match="digest mismatch"):
        verify_kit(tmp_path / "provenance.json")


def test_root_hash_mismatch_raises(tmp_path):
    (tmp_path / "code.py").write_text("print('neutral')", encoding="utf-8")
    build_provenance(tmp_path)
    manifest_path = tmp_path / "provenance.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["root_hash"] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ProvenanceMismatch, match="root hash mismatch"):
        verify_kit(manifest_path)


def test_sha256_of_file_helper(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_text("hello", encoding="utf-8")
    digest = sha256_of_file(path)
    assert len(digest) == 64
