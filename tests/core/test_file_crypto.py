"""Tests for app.core.file_crypto — encryption-at-rest helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.core import file_crypto


@pytest.fixture
def fernet_key() -> str:
    return Fernet.generate_key().decode("ascii")


@pytest.fixture
def other_key() -> str:
    return Fernet.generate_key().decode("ascii")


@pytest.fixture
def encrypted_file(tmp_path: Path, fernet_key: str, monkeypatch):
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", fernet_key)
    path = tmp_path / "doc.pdf"
    plaintext = b"This is a sensitive document."
    file_crypto.write_document(str(path), plaintext)
    return path, plaintext


def test_encryption_disabled_without_env(monkeypatch):
    monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)
    assert file_crypto.encryption_enabled() is False


def test_encryption_enabled_with_valid_key(monkeypatch, fernet_key: str):
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", fernet_key)
    assert file_crypto.encryption_enabled() is True


def test_looks_encrypted_detects_fernet_token(fernet_key: str):
    token = Fernet(fernet_key.encode()).encrypt(b"hello")
    assert file_crypto.looks_encrypted(token) is True


def test_looks_encrypted_rejects_plaintext():
    assert file_crypto.looks_encrypted(b"plain text") is False
    assert file_crypto.looks_encrypted(b"") is False


def test_encrypt_decrypt_round_trip(fernet_key: str, monkeypatch):
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", fernet_key)
    data = b"round-trip data"
    token = file_crypto.encrypt_bytes(data)
    assert file_crypto.looks_encrypted(token) is True
    assert file_crypto.decrypt_bytes(token) == data


def test_encrypt_bytes_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)
    data = b"noop data"
    assert file_crypto.encrypt_bytes(data) == data


def test_decrypt_bytes_noop_for_plaintext_when_key_set(
    fernet_key: str, monkeypatch
):
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", fernet_key)
    data = b"legacy plaintext"
    assert file_crypto.decrypt_bytes(data) == data


def test_write_then_read_document(encrypted_file):
    path, plaintext = encrypted_file
    assert file_crypto.read_document(str(path)) == plaintext


def test_open_plaintext_yields_original_path_for_plaintext(
    tmp_path: Path, monkeypatch
):
    monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)
    path = tmp_path / "plain.txt"
    path.write_bytes(b"plain")
    with file_crypto.open_plaintext(str(path)) as pt_path:
        assert pt_path == str(path)
        assert Path(pt_path).read_bytes() == b"plain"


def test_open_plaintext_yields_temp_path_for_encrypted(encrypted_file):
    path, plaintext = encrypted_file
    with file_crypto.open_plaintext(str(path)) as pt_path:
        assert pt_path != str(path)
        assert Path(pt_path).read_bytes() == plaintext
        suffix = os.path.splitext(pt_path)[1]
        assert suffix == ".pdf"


def test_open_plaintext_cleans_up_temp_file(encrypted_file):
    path, _ = encrypted_file
    temp_path = None
    with file_crypto.open_plaintext(str(path)) as pt_path:
        temp_path = pt_path
        assert Path(temp_path).exists()
    assert not Path(temp_path).exists()


def test_read_document_decrypts_existing_plaintext_after_key_set(
    tmp_path: Path, fernet_key: str, monkeypatch
):
    # Write plaintext before key is configured.
    monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)
    path = tmp_path / "legacy.txt"
    path.write_bytes(b"legacy")

    # Now enable encryption and read.
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", fernet_key)
    assert file_crypto.read_document(str(path)) == b"legacy"


def test_decryption_error_on_wrong_key(
    encrypted_file, other_key: str, monkeypatch
):
    path, _ = encrypted_file
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", other_key)
    with pytest.raises(file_crypto.DecryptionError):
        file_crypto.read_document(str(path))


def test_malformed_key_raises_value_error(monkeypatch):
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(ValueError, match="not a valid Fernet key"):
        file_crypto.encryption_enabled()
