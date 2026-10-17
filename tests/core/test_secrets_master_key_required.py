"""The secrets block must fail hard without CEREBRUM_MASTER_KEY.

Before this, a missing master key silently fell back to a key derived from the
hardcoded constant ``cerebrum_dev_secret_v<N>`` — every deployment that forgot to
set the env var shared one attacker-known key, so every stored secret was
trivially decryptable. Boot must now raise when the key is absent, and succeed
when it is present.
"""

from __future__ import annotations

import base64
import os

import pytest

from app.blocks.secrets import SecretsBlock


@pytest.mark.asyncio
async def test_boot_without_master_key_raises(monkeypatch):
    monkeypatch.delenv("CEREBRUM_MASTER_KEY", raising=False)
    block = SecretsBlock()
    with pytest.raises(RuntimeError) as exc:
        await block._legacy_initialize()
    assert "CEREBRUM_MASTER_KEY" in str(exc.value)


@pytest.mark.asyncio
async def test_boot_with_master_key_succeeds(monkeypatch):
    # A valid 32-byte urlsafe-base64 Fernet key.
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("CEREBRUM_MASTER_KEY", key)
    block = SecretsBlock()
    ok = await block._legacy_initialize()
    assert ok is True
    assert block.cipher is not None


def test_no_hardcoded_dev_secret_constant_in_source():
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[2] / "app" / "blocks" / "secrets.py"
    text = src.read_text(encoding="utf-8")
    assert "cerebrum_dev_secret" not in text, "hardcoded key-derivation constant is back"
    assert "_generate_dev_key" not in text, "constant-derived dev key is back"
