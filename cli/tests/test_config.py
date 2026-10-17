import os
from pathlib import Path

import pytest

from cerebrum_cli import config


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for key in (
        "CEREBRUM_BASE_URL",
        "CEREBRUM_API_KEY",
        "CEREBRUM_DOMAIN",
        "CEREBRUM_INSTANCE_NAME",
        "CEREBRUM_SESSION_ID",
        "CEREBRUM_MODE",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _isolated_config_path(tmp_path, monkeypatch):
    """Point CONFIG_PATH at a non-existent temp file so tests don't see ~/.cerebrum."""
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "not_exists.toml")


def test_load_config_uses_defaults():
    cfg = config.load_config()
    assert cfg["base_url"] == "http://127.0.0.1:8000"
    assert cfg["domain"] == "construction"
    assert cfg["mode"] == "configurator"


def test_load_config_flag_overrides_default():
    cfg = config.load_config(base_url="https://example.com")
    assert cfg["base_url"] == "https://example.com"


def test_load_config_env_overrides_default(monkeypatch):
    monkeypatch.setenv("CEREBRUM_BASE_URL", "https://env.example.com")
    cfg = config.load_config()
    assert cfg["base_url"] == "https://env.example.com"


def test_load_config_flag_overrides_env(monkeypatch):
    monkeypatch.setenv("CEREBRUM_BASE_URL", "https://env.example.com")
    cfg = config.load_config(base_url="https://flag.example.com")
    assert cfg["base_url"] == "https://flag.example.com"


def test_load_config_file_overrides_defaults(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('base_url = "https://file.example.com"\napi_key = "secret"\n')
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    cfg = config.load_config()
    assert cfg["base_url"] == "https://file.example.com"
    assert cfg["api_key"] == "secret"
    assert cfg["mode"] == "configurator"


def test_load_config_mode_from_file(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('mode = "deployed"\n')
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    cfg = config.load_config()
    assert cfg["mode"] == "deployed"


def test_load_config_invalid_mode_defaults_to_configurator(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('mode = "unknown"\n')
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    cfg = config.load_config()
    assert cfg["mode"] == "configurator"


def test_load_config_mode_flag_override(monkeypatch):
    monkeypatch.setenv("CEREBRUM_MODE", "deployed")
    cfg = config.load_config()
    assert cfg["mode"] == "deployed"


def test_resolve_mode():
    assert config.resolve_mode("configurator") == "configurator"
    assert config.resolve_mode("deployed") == "deployed"
    assert config.resolve_mode(None) == "configurator"
    assert config.resolve_mode("") == "configurator"
    assert config.resolve_mode("other") == "configurator"


def test_load_config_env_overrides_file(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('base_url = "https://file.example.com"\n')
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    monkeypatch.setenv("CEREBRUM_BASE_URL", "https://env.example.com")
    cfg = config.load_config()
    assert cfg["base_url"] == "https://env.example.com"


def test_mask():
    assert config.mask("") == "(not set)"
    assert config.mask(None) == "(not set)"
    assert config.mask("short") == "*****"
    assert config.mask("abcdefghij") == "abcd...ghij"


def test_save_config_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    config.save_config(
        {
            "base_url": "https://saved.example.com",
            "api_key": "key",
            "domain": "medical",
            "instance_name": "prod",
            "session_id": "sess_123",
            "mode": "deployed",
        }
    )
    assert path.exists()
    text = path.read_text()
    assert "saved.example.com" in text
    assert "medical" in text
    assert "mode = 'deployed'" in text
