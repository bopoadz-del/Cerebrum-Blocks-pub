"""OpenBox Scoring — multi-factor stock scoring engine, ported from
<private-repo> ``src/services/openbox/engine.ts``.

Ported exactly: the 9-point Piotroski F-score (ROA positive and
improving, CFO positive and above net income, leverage falling, current
ratio rising, share count not rising, margin improving, turnover
improving) with safe division. NEVER the backtest. No network — the
engine scores statement dicts only.
"""
from __future__ import annotations

from typing import Any, Dict

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "openbox_scoring", "status": status, "result": result, "error": error, "detail": detail}


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        import logging
        logging.getLogger(__name__).debug("non-numeric statement value coerced to 0.0: %s", exc)
        return 0.0


def safe_divide(numerator: Any, denominator: Any) -> float:
    d = _num(denominator)
    if d == 0:
        return 0.0
    return _num(numerator) / d


def compute_piotroski(curr_inc, prev_inc, curr_bs, prev_bs, cashflow) -> int:
    if not curr_inc or not prev_inc or not curr_bs or not prev_bs:
        return 0
    score = 0
    curr_roa = safe_divide(curr_inc.get("net_income"), curr_bs.get("total_assets"))
    prev_roa = safe_divide(prev_inc.get("net_income"), prev_bs.get("total_assets"))
    if curr_roa > 0:
        score += 1
    if curr_roa > prev_roa:
        score += 1
    cf = cashflow or {}
    curr_cf = _num(cf.get("total_cash_from_operating_activities") or cf.get("operating_cashflow"))
    if curr_cf > 0:
        score += 1
    if curr_cf > _num(curr_inc.get("net_income")):
        score += 1
    curr_leverage = safe_divide(curr_bs.get("total_liabilities"), curr_bs.get("total_assets"))
    prev_leverage = safe_divide(prev_bs.get("total_liabilities"), prev_bs.get("total_assets"))
    if curr_leverage < prev_leverage:
        score += 1
    curr_ratio = safe_divide(curr_bs.get("total_current_assets"), curr_bs.get("total_current_liabilities"))
    prev_ratio = safe_divide(prev_bs.get("total_current_assets"), prev_bs.get("total_current_liabilities"))
    if curr_ratio > prev_ratio:
        score += 1
    curr_shares = _num(curr_bs.get("common_stock_shares_outstanding"))
    prev_shares = _num(prev_bs.get("common_stock_shares_outstanding"))
    if curr_shares == 0 or prev_shares == 0 or curr_shares <= prev_shares:
        score += 1
    curr_margin = safe_divide(curr_inc.get("operating_income"), curr_inc.get("total_revenue"))
    prev_margin = safe_divide(prev_inc.get("operating_income"), prev_inc.get("total_revenue"))
    if curr_margin > prev_margin:
        score += 1
    curr_turnover = safe_divide(curr_inc.get("total_revenue"), curr_bs.get("total_assets"))
    prev_turnover = safe_divide(prev_inc.get("total_revenue"), prev_bs.get("total_assets"))
    if curr_turnover > prev_turnover:
        score += 1
    return score


class OpenboxScoringBlock(UniversalBlock):
    """Multi-factor stock scoring engine ported from <private-repo>."""

    name = "openbox_scoring"
    version = "1.0.0"
    description = (
        "Multi-factor stock scoring ported from <private-repo> openbox/engine.ts: "
        "the 9-point Piotroski F-score with safe division (ROA positive/improving, "
        "CFO positive and above net income, leverage falling, current ratio rising, "
        "share count not rising, margin and turnover improving). NEVER the backtest. "
        "No network — statement dicts only."
    )
    layer = 3
    tags = ["finance", "scoring", "<private-repo>", "openbox"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "score", "curr_inc": {"net_income": 10}, "prev_inc": {}, "curr_bs": {}, "prev_bs": {}, "cashflow": {}}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "score")).lower()
        try:
            if action == "score":
                score = compute_piotroski(
                    payload.get("curr_inc") or {},
                    payload.get("prev_inc") or {},
                    payload.get("curr_bs") or {},
                    payload.get("prev_bs") or {},
                    payload.get("cashflow") or {},
                )
                return _envelope("ok", {"piotroski_score": score, "max": 9})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["score"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
