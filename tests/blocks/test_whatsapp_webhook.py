"""whatsapp_webhook: donor intent parser + formatter parity, fail-closed scorer.

Donor: <private-repo> src/web/whatsapp.ts.
"""
from __future__ import annotations

import asyncio

import pytest

from app.blocks.whatsapp_webhook import (
    HELP_TEXT,
    SCREENSHOT_FAIL_TEXT,
    WhatsappWebhookBlock,
    escape_xml,
    extract_ticker,
    format_explain,
    format_score,
    parse_intent,
    signal_label,
    strip_keywords,
    twiml,
)


def _run(coro):
    return asyncio.run(coro)


async def _scorer(ticker):
    return {"finalScore": 87.0}


async def _ocr(content, from_):
    return {"tickers": ["AAPL", "MSFT"], "rawText": "AAPL\nMSFT", "corrections": ["J8 -> PDD (known-pattern)"]}


def test_parse_intent_empty_is_help():
    assert parse_intent("", False) == {"type": "help"}
    assert parse_intent("   ", False) == {"type": "help"}


def test_parse_intent_greeting_single_word_help():
    assert parse_intent("hi", False) == {"type": "help"}
    assert parse_intent("hello", False) == {"type": "help"}
    # Donor parity: a multi-word greeting has no ticker and no score words,
    # so it falls through to help too.
    assert parse_intent("hi there", False) == {"type": "help"}


def test_parse_intent_cashtag_score():
    assert parse_intent("$TSLA", False) == {"type": "score", "ticker": "TSLA"}


def test_parse_intent_plain_ticker_score():
    assert parse_intent("AAPL", False) == {"type": "score", "ticker": "AAPL"}


def test_parse_intent_explain():
    assert parse_intent("explain NVDA", False) == {"type": "explain", "ticker": "NVDA"}


def test_parse_intent_score_word_without_ticker():
    intent = parse_intent("score this for me", False)
    assert intent["type"] == "score"
    assert intent.get("ticker") is None
    assert "query" in intent


def test_parse_intent_media_screenshot():
    assert parse_intent("what is this", True) == {"type": "screenshot"}
    assert parse_intent("my portfolio", True) == {"type": "screenshot"}
    assert parse_intent("score this", True) == {"type": "screenshot"}


def test_extract_ticker_common_words_skipped():
    assert extract_ticker("what is the price") is None
    assert extract_ticker("$aapl") == "AAPL"


def test_strip_keywords():
    assert strip_keywords("score the stock price of AAPL?") == "AAPL"


def test_signal_and_grade_bands():
    assert signal_label(90) == "STRONG BUY"
    assert signal_label(84) == "BUY"
    assert signal_label(70) == "BUY"
    assert signal_label(69) == "HOLD"
    assert signal_label(40) == "WATCH"
    assert signal_label(10) == "AVOID"


def test_format_score_with_and_without_quote():
    text = format_score("AAPL", 87.0)
    assert "*AAPL*" in text
    assert "Score: *87/100* (Grade: A)" in text
    assert "Signal: STRONG BUY" in text
    assert "not financial advice" in text
    assert "Price:" not in text
    with_quote = format_score("AAPL", 62.0, {"price": 210.5, "changesPercentage": 1.25})
    assert "Price: $210.50 (+1.25%)" in with_quote
    assert "Signal: HOLD" in with_quote
    negative = format_score("AAPL", 62.0, {"price": 210.5, "changesPercentage": -0.5})
    assert "(-0.50%)" in negative


def test_format_explain():
    text = format_explain("NVDA", 76.0)
    assert "76/100 (BUY)" in text
    assert "not financial advice" in text


def test_escape_xml():
    assert escape_xml("<a & \"b\" 'c'>") == "&lt;a &amp; &quot;b&quot; &apos;c&apos;&gt;"


def test_twiml_shape():
    xml = twiml("hello")
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<Response><Message>hello</Message></Response>" in xml


def test_message_score_refused_without_scorer():
    b = WhatsappWebhookBlock()
    r = _run(b.execute({"action": "message", "body": "AAPL", "from": "whatsapp:+1"}))
    assert r["status"] == "refused"
    assert r["error"] == "score_engine_not_configured"
    assert "Could not score *AAPL* right now." in r["result"]["reply"]
    assert "87" not in r["result"]["reply"]
    assert "<Response>" in r["result"]["twiml"]


def test_message_score_with_scorer():
    b = WhatsappWebhookBlock(scorer=_scorer)
    r = _run(b.execute({"action": "message", "body": "TSLA", "from": "whatsapp:+1"}))
    assert r["status"] == "ok"
    assert r["result"]["score"] == 87.0
    assert "Score: *87/100*" in r["result"]["reply"]


def test_message_explain_with_scorer():
    b = WhatsappWebhookBlock(scorer=_scorer)
    r = _run(b.execute({"action": "message", "body": "explain NVDA", "from": "x"}))
    assert r["status"] == "ok"
    assert "87/100 (STRONG BUY)" in r["result"]["reply"]


def test_message_help_action_and_intent():
    b = WhatsappWebhookBlock()
    r = _run(b.execute({"action": "message", "body": "hi", "from": "x"}))
    assert r["status"] == "ok"
    assert r["result"]["reply"] == HELP_TEXT
    h = _run(b.execute({"action": "help"}))
    assert h["result"]["reply"] == HELP_TEXT


def test_message_nummedia_without_media_url_refused():
    b = WhatsappWebhookBlock(scorer=_scorer)
    r = _run(b.execute({"action": "message", "body": "hi", "from": "x", "num_media": 1}))
    assert r["status"] == "refused"
    assert r["error"] == "media_url_required"


def test_screenshot_without_ocr_refused(monkeypatch):
    b = WhatsappWebhookBlock(scorer=_scorer)

    class _FakeResponse:
        content = b"\xff\xd8\xff"

        def raise_for_status(self):
            return None

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        async def get(self, url, auth=None):
            return _FakeResponse()

    monkeypatch.setattr("app.blocks.whatsapp_webhook.httpx.AsyncClient", _FakeClient)
    r = _run(b.execute({"action": "message", "body": "score this", "from": "x", "media_url": "https://api.twilio.com/media/1"}))
    assert r["status"] == "refused"
    assert r["result"]["reply"] == SCREENSHOT_FAIL_TEXT


def test_screenshot_with_ocr_and_scorer(monkeypatch):
    b = WhatsappWebhookBlock(scorer=_scorer, ocr=_ocr)

    class _FakeResponse:
        content = b"\xff\xd8\xff"

        def raise_for_status(self):
            return None

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        async def get(self, url, auth=None):
            return _FakeResponse()

    monkeypatch.setattr("app.blocks.whatsapp_webhook.httpx.AsyncClient", _FakeClient)
    r = _run(b.execute({"action": "message", "body": "score this", "from": "x", "media_url": "https://api.twilio.com/media/1"}))
    assert r["status"] == "ok"
    assert "Screenshot parsed — 2 ticker(s)" in r["result"]["reply"]
    assert "*AAPL* — 🟢 87/100" in r["result"]["reply"]
    assert "J8 -> PDD" in r["result"]["reply"]


def test_scorer_wired_via_dep():
    b = WhatsappWebhookBlock()
    b.wire("scorer", _scorer)
    r = _run(b.execute({"action": "message", "body": "TSLA", "from": "x"}))
    assert r["status"] == "ok"
    assert r["result"]["score"] == 87.0


def test_parse_intent_action():
    b = WhatsappWebhookBlock()
    r = _run(b.execute({"action": "parse_intent", "body": "$PLTR", "has_media": False}))
    assert r["result"] == {"type": "score", "ticker": "PLTR"}


def test_unknown_action_error():
    b = WhatsappWebhookBlock()
    r = _run(b.execute({"action": "send_twilio"}))
    assert r["status"] == "error"
    assert "unknown action" in r["error"]


@pytest.mark.asyncio
async def test_process_is_async_coroutine():
    b = WhatsappWebhookBlock(scorer=_scorer)
    r = await b.process({"action": "message", "body": "TSLA", "from": "x"})
    assert r["status"] == "ok"
    assert "87/100" in r["result"]["reply"]
