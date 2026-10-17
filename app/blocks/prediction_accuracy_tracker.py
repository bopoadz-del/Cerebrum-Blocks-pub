"""Prediction Accuracy Tracker â€” self-evaluating signal-accuracy analytics,
ported from <private-repo> ``src/services/insights.ts``.

Ported exactly:
- predictedDirection (score >= 70 up, < 45 down, mid-band makes no call),
  actualDirection (to > / < / == from), evaluateSeries walking each
  ticker's time-ordered score/price rows and counting only evaluable,
  non-flat transitions, and rate() â€” hitRate is null when nothing is
  evaluable (the donor explicitly admits null rather than fabricating).
- computeMarketInsights: per-ticker grouping in series order, score trend
  (last - first with >= 2 scores, non-zero only), top gainers (first 5
  positive), top losers (the 5 most negative, reversed), most-alerted.
- computeTickerInsight: latest snapshot, score min/max/avg/trend, accuracy
  over the series; null (refused by the block) when the ticker has no rows.
- buildTickerContextText: the compact model-ready context pack.

The donor reads SQLite via db.ts (getScoreHistorySeries etc.); the block
takes the rows/overview/alert data as input instead. The SQL layer is not
ported. NEVER the backtest.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "prediction_accuracy_tracker", "status": status, "result": result, "error": error, "detail": detail}


def predicted_direction(score: Optional[float]) -> Optional[str]:
    """Map a score to a directional prediction; mid-band scores make no call."""
    if score is None:
        return None
    if score >= 70:
        return "up"
    if score < 45:
        return "down"
    return None


def actual_direction(from_: Optional[float], to: Optional[float]) -> Optional[str]:
    if from_ is None or to is None:
        return None
    if to > from_:
        return "up"
    if to < from_:
        return "down"
    return "flat"


def evaluate_series(rows: List[Dict[str, Any]], acc: Dict[str, int]) -> None:
    """Evaluate score->next-move accuracy over a ticker's time-ordered series."""
    for i in range(len(rows) - 1):
        pred = predicted_direction(rows[i].get("score"))
        if not pred:
            continue
        actual = actual_direction(rows[i].get("price"), rows[i + 1].get("price"))
        if not actual or actual == "flat":
            continue
        acc["evaluated"] += 1
        if pred == actual:
            acc["hits"] += 1


def rate(evaluated: int, hits: int) -> Optional[float]:
    return hits / evaluated if evaluated > 0 else None


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    return float(value)


def compute_market_insights(
    series: List[Dict[str, Any]],
    overview: Optional[Dict[str, Any]] = None,
    alert_counts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    overview = overview or {}
    by_ticker: Dict[str, List[Dict[str, Any]]] = {}
    for row in series:
        by_ticker.setdefault(str(row.get("ticker")), []).append(row)

    acc = {"evaluated": 0, "hits": 0}
    trends: List[Dict[str, Any]] = []
    for ticker, rows in by_ticker.items():
        evaluate_series(rows, acc)
        with_score = [r for r in rows if r.get("score") is not None]
        if len(with_score) >= 2:
            trend = _num(with_score[-1]["score"]) - _num(with_score[0]["score"])
            if trend != 0:
                trends.append({"ticker": ticker, "trend": trend})

    trends.sort(key=lambda t: t["trend"], reverse=True)
    top_gainers = [t for t in trends if t["trend"] > 0][:5]
    top_losers = [t for t in trends if t["trend"] < 0][-5:]
    top_losers.reverse()

    return {
        "dataset": {
            "snapshots": overview.get("total", 0),
            "tickers": overview.get("tickers", len(by_ticker)),
            "since": overview.get("since"),
        },
        "accuracy": {
            "evaluated": acc["evaluated"],
            "hits": acc["hits"],
            "hitRate": rate(acc["evaluated"], acc["hits"]),
        },
        "topGainers": top_gainers,
        "topLosers": top_losers,
        "mostAlerted": list(alert_counts or [])[:5],
    }


def compute_ticker_insight(
    ticker: str,
    rows: List[Dict[str, Any]],
    recent_alerts: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    if not rows:
        return None

    scores = [_num(r.get("score")) for r in rows]
    scores = [s for s in scores if s is not None]
    acc = {"evaluated": 0, "hits": 0}
    evaluate_series(rows, acc)

    last = rows[-1]
    score_trend = scores[-1] - scores[0] if len(scores) >= 2 else None

    return {
        "ticker": ticker.upper(),
        "name": last.get("name"),
        "samples": len(rows),
        "latest": {
            "score": last.get("score"),
            "signal": last.get("signal"),
            "price": last.get("price"),
            "changePct": last.get("change_pct"),
            "at": last.get("created_at"),
        },
        "scoreMin": min(scores) if scores else None,
        "scoreMax": max(scores) if scores else None,
        "scoreAvg": sum(scores) / len(scores) if scores else None,
        "scoreTrend": score_trend,
        "accuracy": {
            "evaluated": acc["evaluated"],
            "hits": acc["hits"],
            "hitRate": rate(acc["evaluated"], acc["hits"]),
        },
        "recentAlerts": [
            {
                "severity": a.get("severity"),
                "direction": a.get("direction"),
                "changePct": a.get("change_pct"),
                "headline": a.get("headline"),
                "at": a.get("created_at"),
            }
            for a in (recent_alerts or [])
        ],
    }


def build_ticker_context_text(ins: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"Ticker: {ins['ticker']}{(' (' + str(ins['name']) + ')') if ins.get('name') else ''}")
    lines.append(f"Recorded snapshots: {ins['samples']}")
    latest = ins.get("latest") or {}
    if latest:
        lines.append(
            f"Latest score: {latest.get('score') if latest.get('score') is not None else 'n/a'} "
            f"(signal {latest.get('signal') or 'n/a'}), price {latest.get('price') if latest.get('price') is not None else 'n/a'}, "
            f"intraday change {latest.get('changePct') if latest.get('changePct') is not None else 'n/a'}%"
        )
    if ins.get("scoreMin") is not None:
        lines.append(
            f"Score range {round(ins['scoreMin'])}-{round(ins.get('scoreMax') or 0)}, "
            f"avg {round(ins['scoreAvg']) if ins.get('scoreAvg') is not None else 'n/a'}, "
            f"trend {round(ins['scoreTrend']) if ins.get('scoreTrend') is not None else 'n/a'}"
        )
    acc = ins.get("accuracy") or {}
    hit_rate = acc.get("hitRate")
    lines.append(
        f"Score signal accuracy: {round(hit_rate * 100)}% over {acc.get('evaluated', 0)} evaluated transitions"
        if hit_rate is not None
        else f"Score signal accuracy: n/a over {acc.get('evaluated', 0)} evaluated transitions"
    )
    recent = ins.get("recentAlerts") or []
    if recent:
        lines.append("Recent alerts:")
        for a in recent:
            headline = a.get("headline")
            suffix = f": {headline}" if headline else ""
            lines.append(f"- {a.get('direction')} {a.get('changePct', 0):.2f}% ({a.get('severity')}){suffix}")
    return "\n".join(lines)


class PredictionAccuracyTrackerBlock(UniversalBlock):
    """Self-evaluating signal-accuracy tracker ported from <private-repo>."""

    name = "prediction_accuracy_tracker"
    version = "1.0.0"
    description = (
        "Self-evaluating signal-accuracy tracker ported from <private-repo> "
        "src/services/insights.ts (real): predictedDirection (>=70 up, <45 "
        "down, mid-band makes no call), time-ordered evaluateSeries over each "
        "ticker's score/price rows, hitRate null when nothing is evaluable "
        "(never fabricated), score trends, top gainers/losers, most-alerted, "
        "and the model-ready context pack. Rows arrive as input; the donor's "
        "SQLite db.ts layer is not ported. NEVER the backtest."
    )
    layer = 3
    tags = ["finance", "analytics", "accuracy", "self-evaluation", "<private-repo>"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "market", "series": [{"ticker": "AAPL", "score": 80, "price": 100}]}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "market")).lower()
        try:
            if action == "market":
                series = payload.get("series")
                if not isinstance(series, list):
                    return _envelope("refused", error="series must be a list of score/price rows", detail={"action": action})
                return _envelope("ok", compute_market_insights(series, payload.get("overview"), payload.get("alert_counts")))
            if action == "ticker":
                ticker = payload.get("ticker")
                series = payload.get("series")
                if not ticker:
                    return _envelope("refused", error="ticker is required", detail={"action": action})
                if not isinstance(series, list):
                    return _envelope("refused", error="series must be a list of score/price rows", detail={"action": action})
                insight = compute_ticker_insight(str(ticker), series, payload.get("recent_alerts"))
                if insight is None:
                    return _envelope("refused", error="no score history for ticker", detail={"ticker": ticker})
                return _envelope("ok", insight)
            if action == "context":
                insight = payload.get("insight")
                if not isinstance(insight, dict):
                    return _envelope("refused", error="insight must be a ticker insight dict", detail={"action": action})
                return _envelope("ok", {"text": build_ticker_context_text(insight)})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["market", "ticker", "context"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
