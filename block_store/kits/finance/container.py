"""Finance & Investment Suite — domain container stub."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict

from app.containers.base import DomainContainer


class FinanceContainer(DomainContainer):
    name = "finance"
    description = "Portfolio analysis, financial modeling, and investment research blocks."
    version = "0.0.0-skeleton"
    system_prompt_file = "finance_expert.txt"

    def __init__(self, kit_root: Path | None = None) -> None:
        self.kit_root = kit_root or Path(__file__).resolve().parent

    def get_actions(self) -> Dict[str, Callable]:
        return {
            "market_quote": self._market_quote,
            "sec_filings": self._sec_filings,
            "health": self._health,
        }

    async def _health(self, input_data: Any, params: Dict) -> Dict:
        return {"status": "healthy", "container": self.name, "version": self.version}

    async def _market_quote(self, input_data: Any, params: Dict) -> Dict:
        block = self._resolve_block("market_data_connector")
        if block is None:
            return {"status": "error", "error": "market_data_connector block unavailable"}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**data, **(params or {})}
        return await block.process(merged, {"action": "fetch", "symbol": merged.get("symbol")})

    async def _sec_filings(self, input_data: Any, params: Dict) -> Dict:
        block = self._resolve_block("sec_edgar_connector")
        if block is None:
            return {"status": "error", "error": "sec_edgar_connector block unavailable"}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**data, **(params or {})}
        return await block.process(merged, {"action": "fetch", "cik": merged.get("cik")})
