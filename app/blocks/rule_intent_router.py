"""Rule-Based Intent Router with learning log â€” ported from
<private-repo> ``src/commands/chat.ts`` + ``src/services/learning.ts`` +
``src/db.ts`` (nl_logs functions).

Ported exactly:
- The deterministic intent classifier: COMMON_WORDS filter, extract
  ticker candidates ($TICKER / standalone 2-5 letter uppercase words,
  validateTicker regex), ticker-only detection, the ordered rule ladder
  (help, portfolio, watchlist show, simulate, metrics, mimic, alert with
  ticker + above/below + price, watchlist add/remove, news, score, search,
  default score), the exp:/pending-flow and expired-mimic-session checks,
  and the fallback path: web search first, then log + "I didn't catch
  that" with the correction keyboard (the donor's correct_intent:...
  callback data).
- logChatIntent / correctChatIntent / getLearningStats / getMissedIntents
  with clampDays (donor: non-finite or out of 1..365 -> 7) and the weekly
  learning-report text.

The executed messaging-bot command handlers are not ported: route() returns the
donor's exact command strings (e.g. "/score AAPL") so the caller can run
them. Company-name search and the DuckDuckGo fallback are dependency
boundaries (wire("search") / wire("web_search")); unwired, the router logs
the fallback and refuses to invent an answer. The intent log is in-process
(the donor's better-sqlite3 nl_logs table is not ported). NEVER the
backtest.
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, List, Optional

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "rule_intent_router", "status": status, "result": result, "error": error, "detail": detail}


COMMON_WORDS = {
    "A", "I", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "IF", "IN", "IS", "IT", "ME", "MY", "NO", "OF", "ON", "OR",
    "SO", "TO", "UP", "US", "WE", "ALL", "AND", "ARE", "BUT", "CAN", "FOR", "HAD", "HAS", "HER", "HIM", "HIS", "HOW",
    "ITS", "NEW", "NOT", "NOW", "OFF", "OLD", "ONE", "OUR", "OUT", "SEE", "SHE", "THE", "TWO", "USE", "WAY", "WHO",
    "YES", "YET", "YOU", "THEY", "THEM", "THAN", "THEN", "THAT", "THIS", "WILL", "WITH", "HAVE", "FROM", "HERE",
    "WANT", "BEEN", "WERE", "SAID", "EACH", "WHICH", "THEIR", "TIME", "VERY", "WHEN", "MUCH", "WOULD", "THERE",
    "ABOUT", "OTHER", "RIGHT", "FIRST", "ALSO", "AFTER", "BACK", "ONLY", "KNOW", "TAKE", "YEAR", "GOOD", "SOME",
    "COME", "MAKE", "WELL", "WORK", "EVEN", "MORE", "LONG", "WHAT", "FIND", "GIVE", "MOST", "OVER", "SUCH", "THINK",
    "WHERE", "BEING", "EVERY", "GREAT", "MIGHT", "SHALL", "STILL", "THOSE", "WHILE", "COULD", "STATE", "NEVER",
    "REALLY", "SHOULD", "THROUGH", "BECAUSE", "BEFORE", "LITTLE", "PEOPLE", "AROUND", "DURING", "PLACE", "THESE",
}

VALID_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,20}$")


def validate_ticker(ticker: str) -> bool:
    return bool(VALID_TICKER_RE.match(ticker))


def sanitize_ticker(ticker: str) -> str:
    return re.sub(r"[^A-Z0-9.\-]", "", ticker.strip().upper())[:20]


def extract_ticker_candidates(text: str) -> List[str]:
    candidates: List[str] = []

    # Pattern 1: $TICKER
    for m in re.findall(r"\$([A-Z]{1,5})", text, flags=re.IGNORECASE):
        ticker = m.upper()
        if validate_ticker(ticker):
            candidates.append(ticker)

    # Pattern 2: standalone 2-5 letter uppercase words (exclude common words)
    for m in re.findall(r"\b[A-Z]{1,5}\b", text):
        ticker = m.upper()
        if len(ticker) >= 2 and ticker not in COMMON_WORDS and validate_ticker(ticker):
            if ticker not in candidates:
                candidates.append(ticker)

    return candidates


def is_ticker_only(text: str) -> Optional[str]:
    trimmed = text.strip()
    match = re.match(r"^\$?([A-Z0-9.\-]{1,20})$", trimmed, flags=re.IGNORECASE)
    if match:
        ticker = sanitize_ticker(match.group(1))
        if validate_ticker(ticker) and ticker not in COMMON_WORDS:
            return ticker
    return None


def clamp_days(days: Any) -> int:
    try:
        d = float(days)
    except (TypeError, ValueError):
        return 7
    if d != d or d < 1 or d > 365:  # NaN check via d != d
        return 7
    return int(d)


def _route_intent(text: str, first_ticker: Optional[str]) -> Dict[str, Any]:
    """The donor's ordered natural-language rule ladder; returns (intent, command)."""
    lower = text.lower().strip()

    if re.search(r"\b(help|commands|what can you do|how to use|menu)\b", lower, flags=re.IGNORECASE):
        return {"intent": "help", "command": "help"}
    if re.search(r"\b(my portfolio|show portfolio|view portfolio|portfolio)\b", lower, flags=re.IGNORECASE):
        return {"intent": "portfolio", "command": "portfolio"}
    if re.search(r"\b(my watchlist|show watchlist|view watchlist|watchlist)\b", lower, flags=re.IGNORECASE):
        if not re.search(r"\b(add|remove|delete)\b", lower, flags=re.IGNORECASE):
            return {"intent": "watchlist", "command": "watchlist"}
    if re.search(r"\b(simulate|monte carlo|projection|forecast|predict)\b", lower, flags=re.IGNORECASE):
        if first_ticker:
            return {"intent": "simulate", "ticker": first_ticker, "command": f"/simulate {first_ticker}"}
    if re.search(r"\b(metrics|risk|volatility|sharpe|drawdown|var|statistics|stats)\b", lower, flags=re.IGNORECASE):
        if first_ticker:
            return {"intent": "metrics", "ticker": first_ticker, "command": f"/metrics {first_ticker}"}
    if re.search(r"\b(mimic|copy investor|copy portfolio|investor strategy|follow investor)\b", lower, flags=re.IGNORECASE):
        return {"intent": "mimic", "command": "mimic"}

    # Alert with ticker + condition + price
    alert_match = re.search(
        r"(?:alert|notify|tell me).{0,20}?\b([A-Z]{1,5})\b.{0,10}?\b(above|below|over|under|higher than|lower than)\b.{0,10}?\$?(\d+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    ) or re.search(
        r"\b([A-Z]{1,5})\b.{0,10}?\b(above|below|over|under|higher than|lower than)\b.{0,10}?\$?(\d+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if alert_match:
        ticker = alert_match.group(1).upper()
        condition = alert_match.group(2).lower()
        price = alert_match.group(3)
        if condition == "over" or condition == "higher than":
            condition = "above"
        if condition == "under" or condition == "lower than":
            condition = "below"
        return {"intent": "alert", "ticker": ticker, "command": f"/alert {ticker} {condition} {price}"}

    add_match = re.search(r"(?:add|put)\s+(.+?)\s+(?:to\s+)?(?:my\s+)?watchlist", lower)
    if add_match and first_ticker:
        return {"intent": "watchlist_add", "ticker": first_ticker, "command": f"/watchlist_add {first_ticker}"}

    remove_match = re.search(r"(?:remove|delete)\s+(.+?)\s+(?:from\s+)?(?:my\s+)?watchlist", lower)
    if remove_match and first_ticker:
        return {"intent": "watchlist_remove", "ticker": first_ticker, "command": f"/watchlist_remove {first_ticker}"}

    if re.search(r"\b(news|headlines|what\s+(?:is|are)\s+(?:the\s+)?news)\b", lower, flags=re.IGNORECASE):
        if first_ticker:
            return {"intent": "news", "ticker": first_ticker, "command": f"/news {first_ticker}"}

    if re.search(r"\b(score|rating|opinion|what do you think|how is|analysis of|analyze)\b", lower, flags=re.IGNORECASE):
        if first_ticker:
            return {"intent": "score", "ticker": first_ticker, "command": f"/score {first_ticker}"}

    if re.search(r"\b(search|find|look up|lookup|info on|information on|about)\b", lower, flags=re.IGNORECASE):
        if first_ticker:
            return {"intent": "search", "ticker": first_ticker, "command": f"/search {first_ticker}"}

    # If we have a ticker but no specific intent matched, default to score
    if first_ticker:
        return {"intent": "default_score", "ticker": first_ticker, "command": f"/score {first_ticker}"}

    return {"intent": "unmatched", "command": None}


FALLBACK_REPLY = (
    "🤦 I didn't catch that.\n\n"
    "You can:\n"
    "• Type a ticker like *AAPL* or *$TSLA* for a quick score\n"
    "• Ask me *\"news for AAPL\"* or *\"score of AAPL\"*\n"
    "• Use /help to see all commands\n\n"
    "_What were you looking for?_"
)

MIMIC_EXPIRED_REPLY = (
    "⚠️ Your mimic session expired (bot restarted).\n\n"
    "Please run /mimic again to select an investor and enter your amount."
)

CORRECTION_INTENTS = ["score", "news", "search", "watchlist", "portfolio", "alert", "simulate", "metrics", "mimic", "other"]


def _learning_report(stats: Dict[str, Any], missed: List[Dict[str, Any]], week_ending: str) -> str:
    fallback_total = stats["fallbackRate"]["total"]
    fallback_pct = f"{(stats['fallbackRate']['fallbacks'] / fallback_total * 100):.1f}" if fallback_total > 0 else "0.0"
    intent_lines = "\n".join(
        f"• {i['detected_intent'] or 'unknown'}: {i['count']} ({i['fallback_pct']}% fallback)"
        for i in stats["intentStats"]
    )
    correction_lines = "\n".join(f"• {c['user_corrected_intent']}: {c['count']}" for c in stats["correctionStats"])
    missed_lines = "\n".join(
        f"• \"{m['raw_message']}\"{' -> ' + m['user_corrected_intent'] if m.get('user_corrected_intent') else ''}"
        for m in missed
    )
    return f"""
📚 *Weekly Learning Report*
_Week ending {week_ending}_

💬 Total chat messages: {stats['totalChat']['count']}
❓ Fallback rate: {fallback_pct}% ({stats['fallbackRate']['fallbacks']}/{fallback_total})

*Detected intents:*
{intent_lines or 'None'}

*User corrections:*
{correction_lines or 'None'}

*Top missed intents:*
{missed_lines or 'None'}
    """.strip()


class RuleIntentRouterBlock(UniversalBlock):
    """Regex intent router with active-learning log, ported from <private-repo>."""

    name = "rule_intent_router"
    version = "1.0.0"
    description = (
        "Rule-based intent router ported from <private-repo> "
        "src/commands/chat.ts + learning.ts + db.ts nl_logs (real): "
        "deterministic $TICKER / uppercase-word extraction, ticker-only "
        "detection, the ordered regex intent ladder (help, portfolio, "
        "watchlist, simulate, metrics, mimic, alert, watchlist add/remove, "
        "news, score, search, default score), the pending-flow / expired "
        "mimic checks, and the fallback path (web search first, then log + "
        "correction keyboard with the donor's correct_intent callback "
        "data). Command handlers are not executed â€” route() returns the "
        "donor's command strings. Company search and DuckDuckGo fallback "
        "are injected (wire search/web_search); unwired, the router logs "
        "the fallback and refuses to invent an answer. Intent log is "
        "in-process. NEVER the backtest."
    )
    layer = 4
    tags = ["nlp", "intent", "router", "learning", "<private-repo>"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "route", "text": "news for AAPL"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._log: List[Dict[str, Any]] = []
        self._pending_mimic: set = set()
        self._pending_experiment: set = set()

    # ---------------------------------------------------------------- db.ts nl_logs

    def _log_chat_intent(
        self,
        chat_id: Any,
        raw_message: str,
        detected_intent: Optional[str] = None,
        extracted_ticker: Optional[str] = None,
        executed_command: Optional[str] = None,
        is_fallback: bool = False,
    ) -> int:
        row = {
            "id": len(self._log) + 1,
            "chat_id": chat_id,
            "raw_message": raw_message,
            "detected_intent": detected_intent,
            "extracted_ticker": extracted_ticker,
            "executed_command": executed_command,
            "is_fallback": 1 if is_fallback else 0,
            "user_corrected_intent": None,
            "user_feedback": None,
            "created_at": time.time(),
        }
        self._log.append(row)
        return row["id"]

    def _correct_chat_intent(self, log_id: int, corrected_intent: str) -> bool:
        for row in self._log:
            if row["id"] == log_id:
                row["user_corrected_intent"] = corrected_intent
                return True
        return False

    def _get_learning_stats(self, days: Any = 7) -> Dict[str, Any]:
        safe_days = clamp_days(days)
        cutoff = time.time() - safe_days * 86400
        rows = [r for r in self._log if r["created_at"] >= cutoff]
        total = len(rows)
        fallbacks = sum(1 for r in rows if r["is_fallback"])
        per_intent: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            key = r["detected_intent"] or "unknown"
            entry = per_intent.setdefault(key, {"count": 0, "fallbacks": 0})
            entry["count"] += 1
            if r["is_fallback"]:
                entry["fallbacks"] += 1
        intent_stats = [
            {"detected_intent": k, "count": v["count"], "fallback_pct": round(v["fallbacks"] / v["count"] * 100, 1)}
            for k, v in per_intent.items()
        ]
        intent_stats.sort(key=lambda i: i["count"], reverse=True)
        per_correction: Dict[str, int] = {}
        for r in rows:
            if r["user_corrected_intent"]:
                per_correction[r["user_corrected_intent"]] = per_correction.get(r["user_corrected_intent"], 0) + 1
        correction_stats = [
            {"user_corrected_intent": k, "count": v}
            for k, v in sorted(per_correction.items(), key=lambda kv: kv[1], reverse=True)
        ]
        return {
            "totalChat": {"count": total},
            "fallbackRate": {"total": total, "fallbacks": fallbacks},
            "intentStats": intent_stats,
            "correctionStats": correction_stats,
        }

    def _get_missed_intents(self, days: Any = 7, limit: int = 50) -> List[Dict[str, Any]]:
        safe_days = clamp_days(days)
        cutoff = time.time() - safe_days * 86400
        missed = [
            r for r in self._log
            if r["is_fallback"] and r["created_at"] >= cutoff
        ]
        missed.sort(key=lambda r: r["created_at"], reverse=True)
        return [
            {k: r[k] for k in ("id", "chat_id", "raw_message", "detected_intent", "user_corrected_intent", "created_at")}
            for r in missed[:limit]
        ]

    # ---------------------------------------------------------------- chat.ts classifier

    def _route(self, text: str, chat_id: Any) -> Dict[str, Any]:
        lower = text.lower().strip()
        tickers = extract_ticker_candidates(text)
        first_ticker = tickers[0] if tickers else None

        # 0. Replacement / removal commands
        if not text.startswith("/") and re.match(r"^(replace|remove|don't like|hate|swap out|drop)\s+", text, flags=re.IGNORECASE):
            self._log_chat_intent(chat_id, text, "replacement", first_ticker, None, False)
            return {"intent": "replacement", "ticker": first_ticker, "command": None}

        # 1. Pending flows (experiment, mimic amount)
        if not text.startswith("/") and chat_id in self._pending_mimic:
            self._log_chat_intent(chat_id, text, "mimic", None, "mimic", False)
            return {"intent": "mimic", "command": "mimic"}

        if not text.startswith("/") and re.match(r"^\$?\d+[\d,]*\.?\d*\s*$", text.strip()):
            self._log_chat_intent(chat_id, text, "mimic_expired", None, None, False)
            return {"intent": "mimic_expired", "command": None, "reply": MIMIC_EXPIRED_REPLY}

        if not text.startswith("/") and lower.startswith("exp:"):
            self._log_chat_intent(chat_id, text, "experiment", None, "experiment", False)
            return {"intent": "experiment", "command": "experiment", "payload": text[4:].strip()}
        if not text.startswith("/") and chat_id in self._pending_experiment:
            self._pending_experiment.discard(chat_id)
            self._log_chat_intent(chat_id, text, "experiment", None, "experiment", False)
            return {"intent": "experiment", "command": "experiment", "payload": text.strip()}

        # 2. Ticker-only message -> score
        ticker_only = is_ticker_only(text)
        if ticker_only:
            self._log_chat_intent(chat_id, text, "ticker_score", ticker_only, "score", False)
            return {"intent": "ticker_score", "ticker": ticker_only, "command": f"/score {ticker_only}"}

        # 3. Natural language parsing
        ruled = _route_intent(text, first_ticker)
        if ruled["intent"] != "unmatched":
            self._log_chat_intent(chat_id, text, ruled["intent"], ruled.get("ticker"), ruled.get("command"), False)
            return ruled

        # 4. Company name search (e.g., "apple", "google") - injected backend
        word_count = len(text.strip().split())
        if re.match(r"^[a-zA-Z0-9\s\.\&\-]+$", text) and 1 < len(text) < 40 and word_count <= 4:
            self._log_chat_intent(chat_id, text, "company_search", None, "search", False)
            return {"intent": "company_search", "command": "search", "query": text.strip()}

        # 5. Fallback
        return {"intent": "fallback", "command": None, "query": text}

    # ---------------------------------------------------------------- block actions

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "route")).lower()
        try:
            if action == "route":
                text = payload.get("text")
                if text is None or not str(text).strip():
                    return _envelope("refused", error="text_required", detail={"action": action})
                chat_id = payload.get("chat_id", 0)
                decision = self._route(str(text), chat_id)

                if decision["intent"] == "fallback":
                    reply = None
                    web_search = self.get_dep("web_search")
                    if callable(web_search):
                        try:
                            results = await web_search(decision["query"], 5)
                        except Exception:  # noqa: BLE001 - search failure falls through to the correction UI
                            results = []
                        if results:
                            log_id = self._log_chat_intent(chat_id, str(text), "fallback", None, None, True)
                            return _envelope("ok", {
                                "intent": "fallback",
                                "is_fallback": True,
                                "search_results": list(results),
                                "log_id": log_id,
                                "corrections": [{"intent": i, "callback": f"correct_intent:{i}:{log_id}"} for i in CORRECTION_INTENTS],
                            })
                    log_id = self._log_chat_intent(chat_id, str(text), "fallback", None, None, True)
                    return _envelope(
                        "refused",
                        result={
                            "reply": FALLBACK_REPLY,
                            "log_id": log_id,
                            "corrections": [{"intent": i, "callback": f"correct_intent:{i}:{log_id}"} for i in CORRECTION_INTENTS],
                        },
                        error="no_intent_match",
                        detail={"action": action},
                    )

                if decision.get("reply"):
                    return _envelope("ok", decision)
                return _envelope("ok", {"intent": decision["intent"], "ticker": decision.get("ticker"), "command": decision.get("command"), "query": decision.get("query"), "payload": decision.get("payload")})
            if action == "correct":
                log_id = int(payload.get("log_id", 0))
                corrected = str(payload.get("corrected_intent") or "")
                if not corrected:
                    return _envelope("refused", error="corrected_intent_required", detail={"action": action})
                if not self._correct_chat_intent(log_id, corrected):
                    return _envelope("refused", error="unknown_log_id", detail={"log_id": log_id})
                return _envelope("ok", {"log_id": log_id, "corrected_intent": corrected})
            if action == "stats":
                return _envelope("ok", self._get_learning_stats(payload.get("days", 7)))
            if action == "missed":
                return _envelope("ok", {"rows": self._get_missed_intents(payload.get("days", 7), int(payload.get("limit", 50)))})
            if action == "report":
                stats = self._get_learning_stats(payload.get("days", 7))
                missed = self._get_missed_intents(payload.get("days", 7), int(payload.get("limit", 15)))
                week_ending = payload.get("week_ending") or time.strftime("%Y-%m-%d", time.gmtime())
                return _envelope("ok", {"text": _learning_report(stats, missed, week_ending)})
            if action == "log":
                log_id = self._log_chat_intent(
                    payload.get("chat_id", 0),
                    str(payload.get("raw_message") or ""),
                    payload.get("detected_intent"),
                    payload.get("extracted_ticker"),
                    payload.get("executed_command"),
                    bool(payload.get("is_fallback", False)),
                )
                return _envelope("ok", {"log_id": log_id})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["route", "correct", "stats", "missed", "report", "log"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
