"""rule_intent_router: donor chat.ts rule ladder + learning-log parity.

Donor: <private-repo> src/commands/chat.ts + src/services/learning.ts +
src/db.ts (nl_logs functions).
"""
from __future__ import annotations

import asyncio

import pytest

from app.blocks.rule_intent_router import (
    RuleIntentRouterBlock,
    clamp_days,
    extract_ticker_candidates,
    is_ticker_only,
    sanitize_ticker,
    validate_ticker,
)


def _run(coro):
    return asyncio.run(coro)


def _block():
    return RuleIntentRouterBlock()


def test_validate_and_sanitize_ticker():
    assert validate_ticker("AAPL") is True
    assert validate_ticker("BRK.B") is True
    assert validate_ticker("AAP L") is False
    assert sanitize_ticker("  aapl! ") == "AAPL"


def test_extract_ticker_candidates():
    assert extract_ticker_candidates("$TSLA") == ["TSLA"]
    assert extract_ticker_candidates("AAPL and MSFT") == ["AAPL", "MSFT"]
    assert extract_ticker_candidates("for the win") == []
    assert extract_ticker_candidates("news for AAPL") == ["AAPL"]


def test_is_ticker_only():
    assert is_ticker_only("AAPL") == "AAPL"
    assert is_ticker_only("$tsla") == "TSLA"
    assert is_ticker_only("hello world") is None
    assert is_ticker_only("AAPL MSFT") is None


def test_route_ticker_only():
    b = _block()
    r = _run(b.execute({"action": "route", "text": "AAPL"}))
    assert r["status"] == "ok"
    assert r["result"]["intent"] == "ticker_score"
    assert r["result"]["command"] == "/score AAPL"


def test_route_help():
    b = _block()
    r = _run(b.execute({"action": "route", "text": "help me please"}))
    assert r["result"]["intent"] == "help"


def test_route_portfolio_and_watchlist():
    b = _block()
    assert _run(b.execute({"action": "route", "text": "show my portfolio"}))["result"]["intent"] == "portfolio"
    assert _run(b.execute({"action": "route", "text": "my watchlist"}))["result"]["intent"] == "watchlist"


def test_route_watchlist_add_remove():
    b = _block()
    add = _run(b.execute({"action": "route", "text": "add AAPL to my watchlist"}))
    assert add["result"]["intent"] == "watchlist_add"
    assert add["result"]["command"] == "/watchlist_add AAPL"
    # Donor rule 0: 'remove ...' is intercepted by the replacement flow first,
    # so the watchlist_remove rule is reached via 'delete ...'.
    rm = _run(b.execute({"action": "route", "text": "delete AAPL from my watchlist"}))
    assert rm["result"]["intent"] == "watchlist_remove"
    assert rm["result"]["command"] == "/watchlist_remove AAPL"
    rep = _run(b.execute({"action": "route", "text": "remove AAPL from my watchlist"}))
    assert rep["result"]["intent"] == "replacement"


def test_route_news_score_search():
    b = _block()
    assert _run(b.execute({"action": "route", "text": "news for AAPL"}))["result"]["command"] == "/news AAPL"
    assert _run(b.execute({"action": "route", "text": "score of AAPL"}))["result"]["command"] == "/score AAPL"
    assert _run(b.execute({"action": "route", "text": "look up MSFT"}))["result"]["command"] == "/search MSFT"


def test_route_simulate_metrics_mimic():
    b = _block()
    assert _run(b.execute({"action": "route", "text": "simulate AAPL"}))["result"]["command"] == "/simulate AAPL"
    assert _run(b.execute({"action": "route", "text": "metrics for AAPL"}))["result"]["command"] == "/metrics AAPL"
    assert _run(b.execute({"action": "route", "text": "mimic buffett"}))["result"]["intent"] == "mimic"


def test_route_alert_patterns():
    b = _block()
    # Donor parity: the /i regex is lazy, so 'when' wins the ticker slot in
    # 'alert me when AAPL is above 250' - the donor produces 'WHEN' too.
    r = _run(b.execute({"action": "route", "text": "alert me when AAPL is above 250"}))
    assert r["result"]["intent"] == "alert"
    assert r["result"]["command"] == "/alert WHEN above 250"
    r0 = _run(b.execute({"action": "route", "text": "alert AAPL above 250"}))
    assert r0["result"]["command"] == "/alert AAPL above 250"
    r2 = _run(b.execute({"action": "route", "text": "tell me if TSLA goes below 100.5"}))
    assert r2["result"]["command"] == "/alert TSLA below 100.5"
    r3 = _run(b.execute({"action": "route", "text": "notify me if NVDA goes over 150"}))
    assert r3["result"]["command"] == "/alert NVDA above 150"


def test_route_replacement_and_experiment():
    b = _block()
    r = _run(b.execute({"action": "route", "text": "replace AAPL with MSFT"}))
    assert r["result"]["intent"] == "replacement"
    r2 = _run(b.execute({"action": "route", "text": "exp: 20% gold"}))
    assert r2["result"]["intent"] == "experiment"
    assert r2["result"]["payload"] == "20% gold"


def test_route_amount_looks_like_expired_mimic():
    b = _block()
    r = _run(b.execute({"action": "route", "text": "100"}))
    assert r["result"]["intent"] == "mimic_expired"
    assert "mimic session expired" in r["result"]["reply"]


def test_route_fallback_refused_and_logged():
    b = _block()
    r = _run(b.execute({"action": "route", "text": "what do I do with my money?"}))
    assert r["status"] == "refused"
    assert r["error"] == "no_intent_match"
    assert "didn't catch that" in r["result"]["reply"]
    assert r["result"]["log_id"] == 1
    assert any(c["callback"] == "correct_intent:score:1" for c in r["result"]["corrections"])
    stats = _run(b.execute({"action": "stats", "days": 7}))
    assert stats["result"]["fallbackRate"] == {"total": 1, "fallbacks": 1}


def test_route_fallback_with_injected_web_search():
    b = _block()

    async def web_search(query, limit):
        return [{"title": "Result", "description": "d", "url": "https://x"}]

    b.wire("web_search", web_search)
    r = _run(b.execute({"action": "route", "text": "what do I do with my money?"}))
    assert r["status"] == "ok"
    assert r["result"]["is_fallback"] is True
    assert len(r["result"]["search_results"]) == 1


def test_correct_action_updates_stats():
    b = _block()
    _run(b.execute({"action": "route", "text": "what do I do with my money?"}))
    ok = _run(b.execute({"action": "correct", "log_id": 1, "corrected_intent": "portfolio"}))
    assert ok["status"] == "ok"
    stats = _run(b.execute({"action": "stats"}))
    assert stats["result"]["correctionStats"] == [{"user_corrected_intent": "portfolio", "count": 1}]
    bad = _run(b.execute({"action": "correct", "log_id": 99, "corrected_intent": "score"}))
    assert bad["status"] == "refused"
    assert bad["error"] == "unknown_log_id"


def test_missed_intents_only_fallbacks():
    b = _block()
    _run(b.execute({"action": "route", "text": "AAPL"}))
    _run(b.execute({"action": "route", "text": "what do I do with my money?"}))
    missed = _run(b.execute({"action": "missed"}))
    assert len(missed["result"]["rows"]) == 1
    assert missed["result"]["rows"][0]["raw_message"] == "what do I do with my money?"


def test_stats_intent_counts_and_fallback_pct():
    b = _block()
    _run(b.execute({"action": "route", "text": "AAPL"}))
    _run(b.execute({"action": "route", "text": "MSFT"}))
    _run(b.execute({"action": "route", "text": "what do I do with my money?"}))
    stats = _run(b.execute({"action": "stats"}))
    intent_stats = {i["detected_intent"]: i for i in stats["result"]["intentStats"]}
    assert intent_stats["ticker_score"]["count"] == 2
    assert intent_stats["fallback"]["count"] == 1
    assert intent_stats["fallback"]["fallback_pct"] == 100.0


def test_report_action():
    b = _block()
    _run(b.execute({"action": "route", "text": "AAPL"}))
    _run(b.execute({"action": "route", "text": "what do I do with my money?"}))
    r = _run(b.execute({"action": "report", "week_ending": "2026-09-20"}))
    assert r["status"] == "ok"
    assert "Weekly Learning Report" in r["result"]["text"]
    assert "Fallback rate: 50.0% (1/2)" in r["result"]["text"]


def test_clamp_days_donor_semantics():
    assert clamp_days(7) == 7
    assert clamp_days(0) == 7
    assert clamp_days(366) == 7
    assert clamp_days("x") == 7
    assert clamp_days(5.9) == 5


def test_route_requires_text():
    b = _block()
    r = _run(b.execute({"action": "route", "text": "   "}))
    assert r["status"] == "refused"
    assert r["error"] == "text_required"


def test_company_search_intent_without_backend():
    # Donor step 4: plain short text with no ticker goes to company-name search.
    b = _block()
    r = _run(b.execute({"action": "route", "text": "apple computer"}))
    assert r["status"] == "ok"
    assert r["result"]["intent"] == "company_search"
    assert r["result"]["query"] == "apple computer"


def test_unknown_action_error():
    b = _block()
    r = _run(b.execute({"action": "train"}))
    assert r["status"] == "error"
    assert "unknown action" in r["error"]


@pytest.mark.asyncio
async def test_process_is_async_coroutine():
    b = _block()
    r = await b.process({"action": "route", "text": "news for AAPL"})
    assert r["status"] == "ok"
    assert r["result"]["command"] == "/news AAPL"
