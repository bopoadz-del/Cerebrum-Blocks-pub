from __future__ import annotations

from unittest import mock

import pytest

from cerebrum_cli import config, main


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


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    return path


def _run_init(argv: list[str], inputs: list[str], monkeypatch):
    """Run ``main.main(["init", *argv])`` with mocked ``input`` and TTY check."""
    input_iter = iter(inputs)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(input_iter))
    monkeypatch.setattr(main.sys.stdin, "isatty", lambda: bool(inputs))
    return main.main(["init", *argv])


def test_init_mode_flag_deployed(cfg_path, monkeypatch, capsys):
    _run_init(["--mode", "deployed"], ["http://x", "key", "domain", "inst", ""], monkeypatch)

    cfg = config.load_config()
    assert cfg["mode"] == "deployed"
    captured = capsys.readouterr()
    assert "defaulting init mode" not in captured.err


def test_init_mode_flag_configurator(cfg_path, monkeypatch, capsys):
    _run_init(["--mode", "configurator"], ["http://x", "key", "domain", "inst", ""], monkeypatch)

    cfg = config.load_config()
    assert cfg["mode"] == "configurator"


def test_init_non_tty_defaults_to_configurator_with_message(cfg_path, monkeypatch, capsys):
    # No inputs means stdin.isatty() returns False, so the interactive prompts
    # are skipped and mode defaults to configurator.
    monkeypatch.setattr(main.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "should-not-be-called")

    main.main(["init"])

    cfg = config.load_config()
    assert cfg["mode"] == "configurator"
    captured = capsys.readouterr()
    assert "stdin is not a TTY" in captured.err
    assert "--mode" in captured.err


def test_init_interactive_prompt_uses_choice(cfg_path, monkeypatch, capsys):
    _run_init([], ["http://x", "key", "domain", "inst", "", "deployed"], monkeypatch)

    cfg = config.load_config()
    assert cfg["mode"] == "deployed"
    captured = capsys.readouterr()
    assert "defaulting init mode" not in captured.err


def test_init_invalid_prompt_choice_defaults_to_configurator(cfg_path, monkeypatch, capsys):
    _run_init([], ["http://x", "key", "domain", "inst", "", "unknown"], monkeypatch)

    cfg = config.load_config()
    assert cfg["mode"] == "configurator"
    captured = capsys.readouterr()
    assert "Invalid mode 'unknown'" in captured.err
