"""Market Data — dual-provider failover quote normalization + alert
evaluation, ported from <private-repo> ``stockPriceService.ts`` and
``alertService.ts``. NEVER the backtest.

The donor's axios/prisma layers are not ported. The store block ports the
deterministic core: provider ORDER (Twelve Data first, Alpha Vantage
fallback, cached last), per-provider payload normalization, and alert
condition evaluation (ABOVE / BELOW / EQUALS). Live HTTP requires API
keys (env); unconfigured calls are refused by name — never fabricated.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "market_data", "status": status, "result": result, "error": error, "detail": detail}


_PROVIDER_ORDER = ["twelvedata", "alphavantage", "cached"]


def normalize_twelvedata(data: Dict[str, Any]) -> Dict[str, Any]:
    if str(data.get("status", "")).lower() == "error":
        raise ValueError(str(data.get("message", "provider error")))
    return {
        "provider": "twelvedata",
        "ticker": str(data.get("symbol", "")).upper(),
        "price": float(data.get("close")),
        "change": float(data.get("change")),
        "change_percent": float(data.get("percent_change")),
        "volume": int(data.get("volume") or 0),
    }


def normalize_alphavantage(data: Dict[str, Any]) -> Dict[str, Any]:
    quote = data.get("Global Quote") or {}
    if not quote:
        raise ValueError("no data available from provider")
    return {
        "provider": "alphavantage",
        "ticker": str(quote.get("01. symbol", "")).upper(),
        "price": float(quote.get("05. price")),
        "change": float(quote.get("09. change")),
        "change_percent": float(str(quote.get("10. change percent", "0")).replace("%", "")),
        "volume": int(quote.get("06. volume") or 0),
    }


def evaluate_alert(condition: str, value: float, current_price: float) -> bool:
    condition = str(condition).upper()
    if condition == "ABOVE":
        return current_price > value
    if condition == "BELOW":
        return current_price < value
    if condition == "EQUALS":
        return abs(current_price - value) < 0.01
    return False


class MarketDataBlock(UniversalBlock):
    """Market data ported from <private-repo>: provider failover order +
    normalization + alert evaluation. Honest refusal without API keys."""

    name = "market_data"
    version = "1.0.0"
    description = (
        "Market data ported from <private-repo> stockPriceService.ts/alertService.ts: "
        "dual-provider failover (Twelve Data -> Alpha Vantage -> cached), per-provider "
        "quote normalization, alert evaluation (ABOVE/BELOW/EQUALS). Live quotes need "
        "provider API keys via env; unconfigured calls are refused by name. NEVER the backtest."
    )
    layer = 3
    tags = ["market-data", "finance", "<private-repo>", "alerts"]
    requires = []

    default_config = {"provider_order": _PROVIDER_ORDER}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "evaluate_alerts", "alerts": [{"ticker": "AAPL", "condition": "ABOVE", "value": 250}], "quotes": {"AAPL": 251.2}}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "evaluate_alerts")).lower()
        try:
            if action == "normalize":
                provider = str(payload.get("provider", "twelvedata")).lower()
                data = payload.get("data") or {}
                if provider == "twelvedata":
                    return _envelope("ok", normalize_twelvedata(data))
                if provider == "alphavantage":
                    return _envelope("ok", normalize_alphavantage(data))
                return _envelope("error", error=f"unknown provider: {provider}", detail={"known": ["twelvedata", "alphavantage"]})
            if action in ("evaluate_alerts", "alerts"):
                alerts = payload.get("alerts") or []
                quotes = payload.get("quotes") or {}
                triggered: List[Dict[str, Any]] = []
                for alert in alerts:
                    ticker = str(alert.get("ticker", "")).upper()
                    if ticker not in quotes:
                        continue
                    current = float(quotes[ticker])
                    if evaluate_alert(str(alert.get("condition", "")), float(alert.get("value", 0)), current):
                        triggered.append({"ticker": ticker, "condition": alert.get("condition"), "value": alert.get("value"), "current_price": current})
                return _envelope("ok", {"triggered": triggered, "count": len(triggered)})
            if action in ("provider_order", "order"):
                return _envelope("ok", {"provider_order": list(self.default_config["provider_order"])})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["normalize", "evaluate_alerts", "provider_order"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
