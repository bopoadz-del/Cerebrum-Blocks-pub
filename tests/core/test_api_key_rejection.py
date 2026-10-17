"""Invalid API keys must be rejected — assert the refusal, not just the accept."""

import pytest

from app.core import api_keys as ak


@pytest.fixture
def manager(tmp_path, monkeypatch):
    return ak.APIKeyManager(db_path=str(tmp_path / "keys.db"))


@pytest.mark.asyncio
async def test_garbage_key_is_rejected(manager):
    assert await manager.validate_key("cb_definitely_not_a_real_key") is None


@pytest.mark.asyncio
async def test_wrong_prefix_is_rejected(manager):
    assert await manager.validate_key("sk_openai_style_key") is None


@pytest.mark.asyncio
async def test_revoked_key_is_rejected(manager):
    created = manager.generate_key(name="t", email="t@example.com")
    key = created["key"]
    assert await manager.validate_key(key) is not None
    manager.revoke_key(created["key_id"])
    assert await manager.validate_key(key) is None
