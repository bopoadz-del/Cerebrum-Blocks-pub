"""Twilio WhatsApp Webhook Handler â€” ported from <private-repo>
``src/web/whatsapp.ts``.

Ported exactly:
- POST /api/whatsapp shape: reads Twilio form fields Body / From /
  NumMedia / MediaUrl0 and replies with the TwiML
  ``<Response><Message>...`` (escapeXml ported 1:1).
- The intent parser (COMMON_WORDS / GREETINGS / extractTicker /
  parseIntent / stripKeywords) and the reply formatters (signalLabel /
  grade / formatScore / formatExplain / HELP_TEXT), including the
  "Experimental study â€” not financial advice." disclaimer.
- handleWhatsAppMessage: help, screenshot, score, explain. The scoring
  engine, quote feed and OCR are dependency boundaries injected via
  wire("scorer") / wire("quote") / wire("ocr") (the donor calls
  computeOpenBoxScore / fmp.getQuote / runOCR directly). With no scorer
  injected the block answers the donor's own failure text
  ("Could not score *T* right now.") â€” it NEVER fabricates a score.
  The screenshot path ports the Twilio media download (httpx, basic auth
  when TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN are configured) and hands
  the bytes to the injected OCR; on any failure it answers the donor's
  screenshot-failure text.
- NEVER the backtest.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional

import httpx

from app.core.universal_base import UniversalBlock
from app.core.http_errors import mark_unavailable


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "whatsapp_webhook", "status": status, "result": result, "error": error, "detail": detail}


COMMON_WORDS = {
    "A", "I", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "IF", "IN", "IS", "IT", "ME", "MY", "NO", "OF", "ON", "OR",
    "SO", "TO", "UP", "US", "WE", "ALL", "AND", "ARE", "BUT", "CAN", "FOR", "HAD", "HAS", "HER", "HIM", "HIS", "HOW",
    "ITS", "NEW", "NOT", "NOW", "OFF", "OLD", "ONE", "OUR", "OUT", "SEE", "SHE", "THE", "TWO", "USE", "WAY", "WHO",
    "YES", "YET", "YOU", "WHY", "HEY", "HII", "THEY", "THEM", "THAN", "THEN", "THAT", "THIS", "WILL", "WITH", "HAVE",
    "FROM", "HELP", "STOP", "MENU", "HOLA", "INFO", "SCORE", "STOCK", "PRICE", "ABOUT", "WORTH", "SHOULD", "BUY",
}

GREETINGS = {"hi", "hello", "hey", "start", "help", "menu", "hola", "yo", "sup"}


def extract_ticker(text: str) -> Optional[str]:
    dollar = re.search(r"\$([A-Za-z]{1,5})\b", text)
    if dollar:
        return dollar.group(1).upper()
    upper = re.findall(r"\b[A-Z]{1,5}\b", text)
    if upper:
        for tok in upper:
            if tok not in COMMON_WORDS:
                return tok
    return None


def strip_keywords(text: str) -> str:
    stripped = re.sub(
        r"\b(explain|why|reason|breakdown|tell me about|score|stock|price|quote|rate|worth|the|of|for|me|about)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(r"[?$]", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip()


def parse_intent(body: str, has_media: bool) -> Dict[str, Any]:
    text = (body or "").strip()
    if not text:
        return {"type": "help"}

    lower = text.lower()
    first_word = lower.split()[0]

    # Greeting -> help
    if first_word in GREETINGS and len(text.split()) == 1:
        return {"type": "help"}

    # Image without text -> treat as screenshot
    if has_media and not text:
        return {"type": "screenshot"}
    if has_media and ("portfolio" in lower or "score this" in lower or "what" in lower):
        return {"type": "screenshot"}

    wants_explain = re.search(r"\b(explain|why|reason|breakdown|tell me about)\b", lower) is not None
    ticker = extract_ticker(text)

    if wants_explain and ticker:
        return {"type": "explain", "ticker": ticker}
    if ticker:
        return {"type": "score", "ticker": ticker}
    if re.search(r"\b(score|stock|price|quote|rate|worth)\b", lower):
        return {"type": "score", "query": strip_keywords(text)}

    return {"type": "help"}


def signal_label(score: float) -> str:
    if score >= 85:
        return "STRONG BUY"
    if score >= 70:
        return "BUY"
    if score >= 55:
        return "HOLD"
    if score >= 40:
        return "WATCH"
    return "AVOID"


def grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def format_score(ticker: str, score: float, quote: Optional[Dict[str, Any]] = None) -> str:
    emoji = "🟢" if score >= 70 else "🟡" if score >= 50 else "🔴"
    price_line = ""
    if quote and quote.get("price") is not None:
        change = quote.get("changesPercentage")
        change_text = (
            f" ({'+' if change >= 0 else ''}{change:.2f}%)"
            if change is not None
            else ""
        )
        price_line = f"\nPrice: ${quote['price']:.2f}{change_text}"
    return (
        f"*{ticker}*{price_line}\nScore: *{score:g}/100* (Grade: {grade(score)})\n"
        f"Signal: {signal_label(score)}\n\n_Experimental study — not financial advice._"
    )


def format_explain(ticker: str, score: float) -> str:
    return (
        f"*{ticker}* — {score:g}/100 ({signal_label(score)})\n\n"
        f'Reply "explain {ticker}" for detailed breakdown.\n\n'
        f"_Experimental study — not financial advice._"
    )


HELP_TEXT = (
    "*StockWise on WhatsApp* 📈\n\n"
    "Send me a ticker to score it:\n"
    "• `AAPL` or `score TSLA`\n"
    "• `explain NVDA` — reasoning\n"
    "• Send a *screenshot* of your portfolio — I will score every stock\n\n"
    "_Experimental study — not financial advice._"
)

SCREENSHOT_FAIL_TEXT = "❌ Failed to process the screenshot. Please try again."


def escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def twiml(reply: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{escape_xml(reply)}</Message></Response>"
    )


class WhatsappWebhookBlock(UniversalBlock):
    """Twilio WhatsApp webhook handler ported from <private-repo>."""

    name = "whatsapp_webhook"
    version = "1.0.0"
    description = (
        "Twilio WhatsApp webhook handler ported from <private-repo> "
        "src/web/whatsapp.ts (real): Twilio Body/From/NumMedia/MediaUrl0 form "
        "fields, the COMMON_WORDS/GREETINGS ticker + intent parser, score/"
        "explain/screenshot reply formatters with the experimental-study "
        "disclaimer, and the TwiML envelope. The OpenBox scoring engine, "
        "quote feed and OCR service are dependency boundaries (wire scorer/"
        "quote/ocr); an unwired scorer answers the donor's could-not-score "
        "text â€” never a fabricated number. Media downloads use httpx with "
        "basic auth when TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN are set. "
        "NEVER the backtest."
    )
    layer = 5
    tags = ["whatsapp", "twilio", "webhook", "messaging", "<private-repo>"]
    requires = []

    default_config = {"twilio_account_sid": "", "twilio_auth_token": ""}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "message", "body": "AAPL", "from": "whatsapp:+1"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None, *, scorer=None, quote=None, ocr=None):
        super().__init__(hal_block=hal_block, config=config)
        self._scorer: Optional[Callable] = scorer
        self._quote: Optional[Callable] = quote
        self._ocr: Optional[Callable] = ocr

    def _scorer_fn(self) -> Optional[Callable]:
        return self._scorer or self.get_dep("scorer") or None

    def _quote_fn(self) -> Optional[Callable]:
        return self._quote or self.get_dep("quote") or None

    def _ocr_fn(self) -> Optional[Callable]:
        return self._ocr or self.get_dep("ocr") or None

    async def _handle_screenshot(self, media_url: str, from_: str) -> str:
        # Donor: download from the Twilio media URL (basic auth when both
        # credentials are set), then runOCR(tmpPath).
        sid = str(self.config.get("twilio_account_sid") or "")
        token = str(self.config.get("twilio_auth_token") or "")
        auth = (sid, token) if sid and token else None
        response = await httpx.AsyncClient(timeout=30).get(media_url, auth=auth)
        response.raise_for_status()
        content = response.content

        ocr = self._ocr_fn()
        if ocr is None:
            raise mark_unavailable(RuntimeError("OCR service not configured"))
        result = await ocr(content, from_)
        tickers = list(result.get("tickers") or [])
        raw_text = str(result.get("rawText") or "")
        corrections = list(result.get("corrections") or [])

        if not tickers:
            preview = raw_text[:200] + "…" if len(raw_text) > 200 else raw_text
            return f"🤖 No tickers found in the image.\n\n_Raw text:_ `{preview}`\n\nTry a clearer screenshot."

        scorer = self._scorer_fn()
        lines: list = []
        for t in tickers[:10]:
            if scorer is not None:
                try:
                    score_result = await scorer(t)
                except Exception:  # noqa: BLE001 - donor catches per-ticker scoring errors
                    score_result = None
                if score_result:
                    emoji = "🟢" if score_result["finalScore"] >= 70 else "🟡" if score_result["finalScore"] >= 50 else "🔴"
                    lines.append(f"*{t}* — {emoji} {score_result['finalScore']:g}/100")
                else:
                    lines.append(f"*{t}* — ❌ could not score")
            else:
                lines.append(f"*{t}* — ❌ could not score")

        correction_text = ""
        if corrections:
            correction_text = "\n\n📝 _OCR corrections:_\n" + "\n".join(f"  {c}" for c in corrections)

        return (
            f"📸 *Screenshot parsed — {len(tickers)} ticker(s):*\n\n"
            f"{chr(10).join(lines)}{correction_text}\n\n_Send another screenshot or type a ticker._"
        )

    async def handle_whatsapp_message(self, body: str, from_: str, media_url: Optional[str] = None) -> Dict[str, Any]:
        has_media = bool(media_url)
        intent = parse_intent(body, has_media)

        if intent["type"] == "help":
            return {"ok": True, "reply": HELP_TEXT, "intent": intent}

        if intent["type"] == "screenshot" and media_url:
            try:
                reply = await self._handle_screenshot(media_url, from_)
                return {"ok": True, "reply": reply, "intent": intent}
            except Exception:  # noqa: BLE001 - donor catch-all answers the failure text
                return {"ok": False, "reply": SCREENSHOT_FAIL_TEXT, "intent": intent, "refusal": "screenshot_failed"}

        ticker = intent.get("ticker") or body.strip().upper()
        if not ticker or len(ticker) < 1 or len(ticker) > 5:
            return {"ok": True, "reply": HELP_TEXT, "intent": intent}

        scorer = self._scorer_fn()
        if scorer is None:
            return {
                "ok": False,
                "reply": f"Could not score *{ticker}* right now. Please try again.",
                "intent": intent,
                "refusal": "score_engine_not_configured",
            }

        score_result = await scorer(ticker)
        if not score_result:
            return {
                "ok": False,
                "reply": f"Could not score *{ticker}* right now. Please try again.",
                "intent": intent,
                "refusal": "score_unavailable",
            }

        score = score_result["finalScore"]

        if intent["type"] == "explain":
            return {"ok": True, "reply": format_explain(ticker, score), "intent": intent, "score": score}

        quote = None
        quote_fn = self._quote_fn()
        if quote_fn is not None:
            try:
                quote = await quote_fn(ticker)
            except Exception:  # noqa: BLE001 - donor ignores quote errors
                quote = None

        return {"ok": True, "reply": format_score(ticker, score, quote), "intent": intent, "score": score}

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "message")).lower()
        try:
            if action == "message":
                body = str(payload.get("body") or payload.get("Body") or "")
                from_ = str(payload.get("from") or payload.get("From") or "unknown")
                num_media = int(payload.get("num_media") or payload.get("NumMedia") or 0)
                media_url = payload.get("media_url") or payload.get("MediaUrl0")
                if num_media > 0 and not media_url:
                    return _envelope("refused", error="media_url_required", detail={"message": "NumMedia>0 requires MediaUrl0"})
                handled = await self.handle_whatsapp_message(body, from_, media_url)
                reply = handled["reply"]
                if handled.get("ok") is False:
                    return _envelope(
                        "refused",
                        result={"reply": reply, "twiml": twiml(reply), "intent": handled["intent"]},
                        error=handled.get("refusal") or "unavailable",
                        detail={"from": from_},
                    )
                return _envelope("ok", {
                    "reply": reply,
                    "twiml": twiml(reply),
                    "intent": handled["intent"],
                    "score": handled.get("score"),
                })
            if action == "parse_intent":
                has_media = bool(payload.get("has_media", False))
                return _envelope("ok", parse_intent(str(payload.get("body") or ""), has_media))
            if action == "help":
                return _envelope("ok", {"reply": HELP_TEXT, "twiml": twiml(HELP_TEXT)})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["message", "parse_intent", "help"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
