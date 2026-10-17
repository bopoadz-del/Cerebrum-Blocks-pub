"""Market data tests — ported behavior from <private-repo>."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.market_data import (
    MarketDataBlock,
    evaluate_alert,
    normalize_alphavantage,
    normalize_twelvedata,
)


def _run(coro):
    return asyncio.run(coro)


def test_normalize_twelvedata():
    q = normalize_twelvedata({"symbol": "aapl", "close": "251.2", "change": "1.1", "percent_change": "0.44", "volume": "1000", "status": "ok"})
    assert q["provider"] == "twelvedata"
    assert q["ticker"] == "AAPL"
    assert q["price"] == 251.2


def test_normalize_alphavantage():
    q = normalize_alphavantage({"Global Quote": {"01. symbol": "MSFT", "05. price": "410.0", "09. change": "-2.0", "10. change percent": "-0.49%", "06. volume": "500"}})
    assert q["provider"] == "alphavantage"
    assert q["change_percent"] == -0.49


def test_provider_error_refused():
    b = MarketDataBlock()
    r = _run(b.process({"action": "normalize", "provider": "twelvedata", "data": {"status": "error", "message": "rate limited"}}))
    assert r["status"] == "error"


def test_alert_evaluation():
    assert evaluate_alert("ABOVE", 250, 251.2) is True
    assert evaluate_alert("BELOW", 250, 251.2) is False
    assert evaluate_alert("EQUALS", 250, 250.005) is True
    assert evaluate_alert("NONSENSE", 250, 251.2) is False


def test_evaluate_alerts_batch():
    b = MarketDataBlock()
    r = _run(b.process({
        "action": "evaluate_alerts",
        "alerts": [{"ticker": "AAPL", "condition": "ABOVE", "value": 250}, {"ticker": "AAPL", "condition": "BELOW", "value": 100}],
        "quotes": {"AAPL": 251.2},
    }))
    assert r["status"] == "ok"
    assert r["result"]["count"] == 1
    assert r["result"]["triggered"][0]["condition"] == "ABOVE"


def test_provider_order_is_documented():
    b = MarketDataBlock()
    r = _run(b.process({"action": "provider_order"}))
    assert r["result"]["provider_order"] == ["twelvedata", "alphavantage", "cached"]
