"""ticker_ocr_fuzzy: donor extraction-pass parity + refusal paths.

Donor: <private-repo> src/services/ocr.ts.
"""
from __future__ import annotations

import asyncio

import pytest

from app.blocks.ticker_ocr_fuzzy import (
    TickerOcrFuzzyBlock,
    extract_tickers,
    fuzzy_match_ticker,
    levenshtein,
    normalize_ticker_candidate,
    ticker_candidate,
    validate_ticker_with_correction,
)


def _run(coro):
    return asyncio.run(coro)


def test_normalize_ticker_candidate():
    assert normalize_ticker_candidate("aapl") == "AAPL"
    assert normalize_ticker_candidate("123AAPL") == "AAPL"
    assert normalize_ticker_candidate("AAPL.") == "AAPL"
    assert normalize_ticker_candidate("AAPLXYZQ") == "AAPLXY"  # slice(0, 6)


def test_levenshtein_dp():
    assert levenshtein("AAPL", "AAPL") == 0
    assert levenshtein("AAPL", "APL") == 1
    assert levenshtein("AAPL", "MSFT") == 4


def test_known_corrections():
    assert validate_ticker_with_correction("J8") == "PDD"
    assert validate_ticker_with_correction("SG0L") == "SGOL"
    assert validate_ticker_with_correction("XE1") == "XEL"
    assert validate_ticker_with_correction("S0") == "SO"
    assert validate_ticker_with_correction("TSL4") == "TSLA"


def test_common_words_and_false_positives_rejected():
    assert validate_ticker_with_correction("PRICE") is None
    assert validate_ticker_with_correction("NASDAQ") is None
    assert validate_ticker_with_correction("FIDELITY") is None


def test_confusion_map_corrections():
    # 0 -> O family
    assert validate_ticker_with_correction("SGO1") == "SGOL"  # 1->I? no: I->L family via confusion
    assert validate_ticker_with_correction("AAP1") == "AAPL"


def test_fuzzy_match_donor_order():
    assert fuzzy_match_ticker("AAPL") == "AAPL"
    # First distance-1 universe hit in stock-universe order is AAPL
    assert fuzzy_match_ticker("APL") == "AAPL"
    assert fuzzy_match_ticker("ZZZZZ") is None
    assert fuzzy_match_ticker("A") is None


def test_ticker_candidate_first_token_only():
    # FIX v2: table lines keep the first word, never the concatenated numbers
    assert ticker_candidate("XEL              3,249.20 81.23") == "XEL"
    assert ticker_candidate("AAPL 210.5") == "AAPL"
    assert ticker_candidate("3,249.20 81.23") is None
    assert ticker_candidate("") is None


def test_extract_cashtag_pass():
    res = extract_tickers("$TSLA and $nvda")
    assert "TSLA" in res["tickers"]
    assert "NVDA" in res["tickers"]


def test_extract_structural_pass():
    res = extract_tickers("AAPL\nApple Inc.\nMSFT\nMicrosoft Corp.")
    assert res["tickers"][0] == "AAPL"
    assert "MSFT" in res["tickers"]


def test_extract_known_pattern_pass():
    res = extract_tickers("portfolio has J8 position")
    assert "PDD" in res["tickers"]
    assert any("J8 -> PDD" in c for c in res["corrections"])


def test_extract_correction_logged():
    res = extract_tickers("SG0L")
    assert res["tickers"] == ["SGOL"]
    assert "SG0L -> SGOL" in res["corrections"][0]


def test_extract_no_tickers():
    res = extract_tickers("the quick brown fox")
    assert res["tickers"] == []


def test_extract_dedupes():
    res = extract_tickers("AAPL AAPL $AAPL")
    assert res["tickers"].count("AAPL") == 1


def test_block_extract_action():
    b = TickerOcrFuzzyBlock()
    r = _run(b.execute({"action": "extract", "text": "J8 $TSLA"}))
    assert r["status"] == "ok"
    assert set(r["result"]["tickers"]) == {"PDD", "TSLA"}


def test_block_extract_custom_universe():
    # The pipeline is ticker-shaped (1-5 letters, uppercase patterns); a
    # custom universe overrides VALID_TICKERS for validation/fuzzy only.
    b = TickerOcrFuzzyBlock()
    r = _run(b.execute({"action": "extract", "text": "TSLA NVDA", "valid_tickers": ["TSLA"]}))
    assert r["result"]["tickers"] == ["TSLA"]
    r2 = _run(b.execute({"action": "validate", "candidate": "TSLA", "valid_tickers": ["TSLA"]}))
    assert r2["result"]["corrected"] == "TSLA"


def test_block_validate_and_fuzzy_actions():
    b = TickerOcrFuzzyBlock()
    v = _run(b.execute({"action": "validate", "candidate": "J8"}))
    assert v["result"]["corrected"] == "PDD"
    f = _run(b.execute({"action": "fuzzy", "candidate": "APL"}))
    assert f["result"]["match"] == "AAPL"


def test_block_universe_action():
    b = TickerOcrFuzzyBlock()
    r = _run(b.execute({"action": "universe"}))
    assert r["status"] == "ok"
    assert r["result"]["count"] == 386


def test_image_input_refused():
    b = TickerOcrFuzzyBlock()
    r = _run(b.execute({"action": "run_ocr", "image_path": "/tmp/x.jpg"}))
    assert r["status"] == "refused"
    assert r["error"] == "vision_backend_not_ported"
    r2 = _run(b.execute({"action": "score_tickers", "tickers": ["AAPL"]}))
    assert r2["status"] == "refused"
    assert r2["error"] == "vision_backend_not_ported"


def test_extract_requires_text():
    b = TickerOcrFuzzyBlock()
    r = _run(b.execute({"action": "extract"}))
    assert r["status"] == "refused"
    assert r["error"] == "text_required"


def test_unknown_action_error():
    b = TickerOcrFuzzyBlock()
    r = _run(b.execute({"action": "vision"}))
    assert r["status"] == "error"
    assert "unknown action" in r["error"]


@pytest.mark.asyncio
async def test_process_is_async_coroutine():
    b = TickerOcrFuzzyBlock()
    r = await b.process({"action": "extract", "text": "SG0L"})
    assert r["status"] == "ok"
    assert r["result"]["tickers"] == ["SGOL"]
