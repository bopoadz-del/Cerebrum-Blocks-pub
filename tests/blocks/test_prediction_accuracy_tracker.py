"""prediction_accuracy_tracker: donor insights.ts parity + refusal paths.

Donor: <private-repo> src/services/insights.ts.
"""
from __future__ import annotations

import asyncio

import pytest

from app.blocks.prediction_accuracy_tracker import (
    PredictionAccuracyTrackerBlock,
    actual_direction,
    build_ticker_context_text,
    compute_market_insights,
    compute_ticker_insight,
    evaluate_series,
    predicted_direction,
    rate,
)


def _run(coro):
    return asyncio.run(coro)


def test_predicted_direction_bands():
    assert predicted_direction(70) == "up"
    assert predicted_direction(100) == "up"
    assert predicted_direction(69) is None
    assert predicted_direction(45) is None
    assert predicted_direction(44) == "down"
    assert predicted_direction(None) is None


def test_actual_direction():
    assert actual_direction(100, 110) == "up"
    assert actual_direction(110, 100) == "down"
    assert actual_direction(100, 100) == "flat"
    assert actual_direction(None, 100) is None
    assert actual_direction(100, None) is None


def test_evaluate_series_hits_misses_and_skips():
    rows = [
        {"score": 80, "price": 100},   # up -> 110: hit
        {"score": 40, "price": 110},   # down -> 105: hit
        {"score": 60, "price": 105},   # mid-band: skipped
        {"score": 90, "price": 105},   # up -> 105: flat skipped
        {"score": 30, "price": 105},   # down -> 99: hit
        {"score": 30, "price": 99},    # (no next row)
    ]
    acc = {"evaluated": 0, "hits": 0}
    evaluate_series(rows, acc)
    assert acc == {"evaluated": 3, "hits": 3}


def test_evaluate_series_miss_counts_evaluated_not_hit():
    rows = [
        {"score": 85, "price": 100},
        {"score": 85, "price": 90},  # predicted up, actual down -> miss
    ]
    acc = {"evaluated": 0, "hits": 0}
    evaluate_series(rows, acc)
    assert acc == {"evaluated": 1, "hits": 0}


def test_rate_null_when_nothing_evaluable():
    assert rate(0, 0) is None
    assert rate(2, 1) == 0.5


def test_market_insights_nulls_and_trends():
    series = [
        {"ticker": "AAPL", "score": 50, "price": 100},
        {"ticker": "AAPL", "score": 80, "price": 105},
        {"ticker": "MSFT", "score": 80, "price": 200},
        {"ticker": "MSFT", "score": 40, "price": 190},
    ]
    res = compute_market_insights(series, {"total": 4, "tickers": 2, "since": "2026-01-01"}, [{"ticker": "AAPL", "count": 3}])
    assert res["dataset"] == {"snapshots": 4, "tickers": 2, "since": "2026-01-01"}
    # AAPL 50 is mid-band (no call); MSFT 80 predicted up but fell -> the one miss.
    assert res["accuracy"]["hitRate"] == 0.0
    assert res["accuracy"]["evaluated"] == 1
    assert res["accuracy"]["hits"] == 0
    assert res["topGainers"] == [{"ticker": "AAPL", "trend": 30}]
    assert res["topLosers"] == [{"ticker": "MSFT", "trend": -40}]
    assert res["mostAlerted"] == [{"ticker": "AAPL", "count": 3}]


def test_market_insights_hit_rate_null_admitted():
    # Mid-band scores only: nothing evaluable -> honest null, never a number.
    series = [
        {"ticker": "AAPL", "score": 60, "price": 100},
        {"ticker": "AAPL", "score": 55, "price": 105},
    ]
    res = compute_market_insights(series)
    assert res["accuracy"]["hitRate"] is None
    assert res["accuracy"]["evaluated"] == 0
    assert res["topGainers"] == []
    # The score trend is still computed (last - first = -5) even when nothing
    # is evaluable - donor parity.
    assert res["topLosers"] == [{"ticker": "AAPL", "trend": -5.0}]


def test_market_insights_trend_zero_excluded():
    series = [
        {"ticker": "AAPL", "score": 60, "price": 100},
        {"ticker": "AAPL", "score": 60, "price": 105},
    ]
    res = compute_market_insights(series)
    assert res["topGainers"] == [] and res["topLosers"] == []


def test_ticker_insight_shape():
    rows = [
        {"score": 80, "price": 100, "signal": "BUY", "name": "Apple Inc.", "change_pct": 1.5, "created_at": "2026-01-01T00:00:00Z"},
        {"score": 60, "price": 105, "signal": "HOLD", "name": "Apple Inc.", "change_pct": 0.5, "created_at": "2026-01-02T00:00:00Z"},
    ]
    ins = compute_ticker_insight("aapl", rows, [{"severity": "high", "direction": "up", "change_pct": 5.0, "headline": "x", "created_at": "t"}])
    assert ins["ticker"] == "AAPL"
    assert ins["samples"] == 2
    assert ins["latest"]["score"] == 60
    assert ins["scoreMin"] == 60 and ins["scoreMax"] == 80
    assert ins["scoreAvg"] == 70.0
    assert ins["scoreTrend"] == -20
    assert ins["accuracy"]["hitRate"] == 1.0  # predicted up, price 100 -> 105 rose
    assert ins["recentAlerts"][0]["severity"] == "high"


def test_ticker_insight_hit():
    rows = [
        {"score": 80, "price": 100},
        {"score": 80, "price": 105},
    ]
    ins = compute_ticker_insight("AAPL", rows)
    assert ins["accuracy"]["hitRate"] == 1.0


def test_ticker_insight_empty_rows_none():
    assert compute_ticker_insight("AAPL", []) is None


def test_context_text_admits_n_a():
    ins = compute_ticker_insight("AAPL", [{"score": 60, "price": 100}])
    text = build_ticker_context_text(ins)
    assert "Score signal accuracy: n/a over 0 evaluated transitions" in text
    ins2 = compute_ticker_insight("AAPL", [{"score": 80, "price": 100}, {"score": 80, "price": 110}])
    text2 = build_ticker_context_text(ins2)
    assert "Score signal accuracy: 100% over 1 evaluated transitions" in text2


def test_block_market_action():
    b = PredictionAccuracyTrackerBlock()
    r = _run(b.execute({"action": "market", "series": [
        {"ticker": "AAPL", "score": 80, "price": 100},
        {"ticker": "AAPL", "score": 80, "price": 110},
    ]}))
    assert r["status"] == "ok"
    assert r["result"]["accuracy"]["hitRate"] == 1.0


def test_block_ticker_refused_without_rows():
    b = PredictionAccuracyTrackerBlock()
    r = _run(b.execute({"action": "ticker", "ticker": "ZZZZ", "series": []}))
    assert r["status"] == "refused"
    assert r["error"] == "no score history for ticker"


def test_block_ticker_action():
    b = PredictionAccuracyTrackerBlock()
    r = _run(b.execute({"action": "ticker", "ticker": "AAPL", "series": [{"score": 80, "price": 100}]}))
    assert r["status"] == "ok"
    assert r["result"]["samples"] == 1
    assert r["result"]["accuracy"]["hitRate"] is None


def test_block_market_requires_list():
    b = PredictionAccuracyTrackerBlock()
    r = _run(b.execute({"action": "market", "series": "AAPL"}))
    assert r["status"] == "refused"


def test_block_context_action():
    b = PredictionAccuracyTrackerBlock()
    ins = compute_ticker_insight("AAPL", [{"score": 60, "price": 100}])
    r = _run(b.execute({"action": "context", "insight": ins}))
    assert r["status"] == "ok"
    assert "Ticker: AAPL" in r["result"]["text"]


def test_unknown_action_error():
    b = PredictionAccuracyTrackerBlock()
    r = _run(b.execute({"action": "predict"}))
    assert r["status"] == "error"
    assert "unknown action" in r["error"]


@pytest.mark.asyncio
async def test_process_is_async_coroutine():
    b = PredictionAccuracyTrackerBlock()
    r = await b.process({"action": "market", "series": []})
    assert r["status"] == "ok"
    assert r["result"]["accuracy"]["hitRate"] is None
