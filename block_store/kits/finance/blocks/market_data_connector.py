"""Market data connector stub — inherits BaseConnector."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from app.blocks.core.base_connector import BaseConnector
from app.core.connector_events import ConnectorEvent


class MarketDataConnectorBlock(BaseConnector):
    """Stub for market data provider integration (quotes, OHLCV)."""

    name = "market_data_connector"
    version = "0.1.0-skeleton"
    description = "Market data quotes connector (stub)"
    layer = 3
    tags = ["finance", "connector", "market", "quotes", "stub"]
    connector_source = "market_data"

    default_config = {
        "market_data_api_key": os.getenv("MARKET_DATA_API_KEY", ""),
        "market_data_provider": os.getenv("MARKET_DATA_PROVIDER", "stub"),
        "timeout_seconds": 30,
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"symbols": ["AAPL", "MSFT"], "interval": "1d"}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "event", "type": "json", "label": "Connector Event"},
                {"name": "quotes", "type": "json", "label": "Quotes"},
            ],
        },
        "params": [
            {"name": "action", "type": "select", "label": "Action", "options": ["fetch", "auth", "health"], "default": "fetch"},
            {"name": "symbol", "type": "text", "label": "Symbol"},
            {"name": "provider", "type": "text", "label": "Provider"},
        ],
        "quick_actions": [
            {"icon": "📈", "label": "Fetch quote", "prompt": "Fetch market quote for a symbol"},
        ],
    }

    def _provider(self) -> str:
        return (
            self.config.get("market_data_provider")
            or os.getenv("MARKET_DATA_PROVIDER", "stub")
        )

    def _api_key(self) -> str:
        return self.config.get("market_data_api_key") or os.getenv("MARKET_DATA_API_KEY", "")

    async def authenticate(self) -> Dict[str, Any]:
        provider = self._provider()
        if provider == "stub":
            return {"authenticated": True, "method": "stub", "provider": provider}
        key = self._api_key()
        if not key:
            return {"authenticated": False, "error": "MARKET_DATA_API_KEY not configured"}
        return {"authenticated": True, "method": "api_key", "provider": provider}

    async def fetch_raw(self, input_data: Any, params: Dict) -> Any:
        data = input_data if isinstance(input_data, dict) else {}
        symbols = data.get("symbols") or []
        symbol = params.get("symbol") or data.get("symbol")
        if symbol:
            symbols = [symbol]
        if not symbols:
            raise ValueError("symbol or symbols required for market data fetch")

        provider = params.get("provider") or self._provider()
        if provider == "stub" or not self._api_key():
            return {
                "stub": True,
                "provider": provider,
                "quotes": [
                    {
                        "symbol": s,
                        "price": 100.0,
                        "currency": "USD",
                        "change_pct": 0.5,
                        "timestamp": "2024-01-01T00:00:00Z",
                    }
                    for s in symbols
                ],
            }

        url = f"https://api.{provider}.example.com/v1/quotes"
        headers = {"Authorization": f"Bearer {self._api_key()}"}
        timeout = float(self.config.get("timeout_seconds", 30))
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers, params={"symbols": ",".join(symbols)})
            resp.raise_for_status()
            return resp.json()

    def normalize(
        self, raw: Any, params: Optional[Dict] = None, input_data: Any = None
    ) -> ConnectorEvent:
        quotes = []
        if isinstance(raw, dict):
            quotes = raw.get("quotes") or raw.get("data") or []
        return ConnectorEvent(
            source=self.connector_source,
            event_type="market.quote.fetched",
            payload=raw if isinstance(raw, dict) else {"data": raw},
            normalized_data={
                "count": len(quotes) if isinstance(quotes, list) else 0,
                "quotes": quotes,
                "provider": self._provider(),
            },
            tags=["finance", "market", "quotes"],
        )
