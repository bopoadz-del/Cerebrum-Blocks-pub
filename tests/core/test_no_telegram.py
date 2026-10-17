"""Telegram is removed from the platform. It must stay removed.

Owner directive (2026-08-02, after repeated prior requests): no Telegram
bot, no Telegram channel, no Telegram integration anywhere. Previous
removals were partial — the bot was moved into ``block_store/`` instead of
deleted, the notification block kept ``telegram`` as its *default* channel
(which, with the handler gone, made the default silently broken), and the
router schema still advertised it. A later pass still missed the *signed
block-registry manifest*, which advertised Telegram as a channel and shipped
``telegram`` example payloads to the UI, plus a ``parse_mode`` field (a
Telegram-only concept) left in the notification block's input schema. This
test now scans code AND registry metadata AND the parse_mode vestige so a
partial removal can never look complete again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# Per-directory scan rules. Code is scanned everywhere. JSON is scanned only
# where it is *integration metadata* (app config + block-registry manifests
# served to users and baked into signed manifests). ``block_store`` JSON is
# code-only: it holds eval/benchmark datasets (e.g. legal contract corpora)
# whose text legitimately contains the word "telegram" and must not trip the
# guard. Docs are excluded too: a historical audit note recording the removal
# legitimately says "telegram".
SCAN_RULES = {
    "app": ("*.py", "*.json"),
    "block_registry": ("*.py", "*.json"),
    "block_store": ("*.py",),
}


def test_no_telegram_anywhere_in_source():
    offenders = []
    for base, patterns in SCAN_RULES.items():
        root = REPO_ROOT / base
        if not root.is_dir():
            continue
        for pattern in patterns:
            for path in root.rglob(pattern):
                text = path.read_text(encoding="utf-8", errors="ignore")
                if "telegram" in text.lower():
                    offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Telegram references found — the owner has asked repeatedly for "
        f"complete removal: {sorted(set(offenders))}"
    )


def test_no_telegram_parse_mode_vestige():
    """``parse_mode`` is a Telegram-only field. It must not survive in the
    notification block's schema or its signed registry manifest."""
    offenders = []
    candidates = [
        REPO_ROOT / "app" / "blocks" / "notification.py",
        REPO_ROOT / "block_registry" / "notification" / "block.json",
    ]
    for path in candidates:
        if path.is_file() and "parse_mode" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"Telegram-only 'parse_mode' vestige found in: {offenders}"


def test_no_telegram_env_knob_documented():
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").lower()
    assert "telegram" not in text


def test_notification_send_requires_an_explicit_channel():
    """The old default channel was telegram; with the handler long gone the
    default was a guaranteed error. No silent default may replace it."""
    from app.routers.notification import SendRequest

    with pytest.raises(Exception):
        SendRequest(message="hi")  # no channel — must not silently pick one

    req = SendRequest(channel="email", message="hi")
    assert req.channel == "email"


@pytest.mark.asyncio
async def test_notification_block_rejects_telegram_channel():
    from app.blocks.notification import NotificationBlock

    block = NotificationBlock()
    result = await block._send({"channel": "telegram", "message": "hi"})
    assert result["status"] == "error"
    assert "telegram" in result["error"].lower() or "unknown" in result["error"].lower()
