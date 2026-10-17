"""RFM Guest Segmentation â€” deterministic recency/frequency/monetary scoring,
ported from <private-repo>-v2 ``guest_intelligence/segmentation.py``.

Ported exactly: rfm_score()'s bucket ladder (recency <= thresholds,
frequency/monetary >= thresholds) and the segment labels
(champions / loyal / promising / at_risk) with ``advisory: True`` on every
result, plus the RfmScorer threshold holder. The donor's dead first
``f = bucket(-frequency + 1, ...)`` assignment is dropped: it is
immediately overwritten by the deterministic ladder and never observable.

The donor is pure advisory analytics over numbers; this block refuses
(non-numeric or absent inputs) rather than guessing a bucket.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "guest_rfm_segmentation", "status": status, "result": result, "error": error, "detail": detail}


def _as_float(value: Any, name: str) -> float:
    if value is None or (isinstance(value, bool)):
        raise ValueError(f"{name} is required and must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric, got {value!r}") from None


def rfm_score(
    recency_days: float,
    frequency: int,
    monetary: float,
    *,
    r_thresholds: Tuple[float, float] = (30.0, 90.0),
    f_thresholds: Tuple[int, int] = (5, 2),
    m_thresholds: Tuple[float, float] = (5000.0, 1500.0),
) -> Dict[str, Any]:
    r = 3 if recency_days <= r_thresholds[0] else 2 if recency_days <= r_thresholds[1] else 1
    f = 3 if frequency >= f_thresholds[0] else 2 if frequency >= f_thresholds[1] else 1
    m = 3 if monetary >= m_thresholds[0] else 2 if monetary >= m_thresholds[1] else 1
    total = r + f + m
    segment = "champions" if total >= 8 else "loyal" if total >= 6 else "promising" if total >= 4 else "at_risk"
    return {
        "r": r,
        "f": f,
        "m": m,
        "score": total,
        "segment": segment,
        "advisory": True,
    }


class RfmScorer:
    def __init__(
        self,
        r_thresholds: Tuple[float, float] = (30.0, 90.0),
        f_thresholds: Tuple[int, int] = (5, 2),
        m_thresholds: Tuple[float, float] = (5000.0, 1500.0),
    ) -> None:
        self.r_thresholds = r_thresholds
        self.f_thresholds = f_thresholds
        self.m_thresholds = m_thresholds

    def score(self, recency_days: float, frequency: int, monetary: float) -> Dict[str, Any]:
        return rfm_score(
            recency_days,
            frequency,
            monetary,
            r_thresholds=self.r_thresholds,
            f_thresholds=self.f_thresholds,
            m_thresholds=self.m_thresholds,
        )


class GuestRfmSegmentationBlock(UniversalBlock):
    """Deterministic RFM guest segmentation ported from <private-repo>-v2."""

    name = "guest_rfm_segmentation"
    version = "1.0.0"
    description = (
        "RFM guest segmentation ported from <private-repo>-v2 "
        "guest_intelligence/segmentation.py: rfm_score() bucket ladder over "
        "recency (<=30/90 days), frequency (>=5/2 stays) and monetary "
        "(>=5000/1500) with the champions/loyal/promising/at_risk segment "
        "labels; every result is marked advisory (no trained model). Real "
        "deterministic analytics; non-numeric or missing inputs are refused, "
        "never guessed."
    )
    layer = 3
    tags = ["hotel", "crm", "segmentation", "rfm", "guest", "hotelops-v2"]
    requires = []

    default_config = {
        "r_thresholds": [30.0, 90.0],
        "f_thresholds": [5, 2],
        "m_thresholds": [5000.0, 1500.0],
    }

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "score", "recency_days": 12, "frequency": 6, "monetary": 9000}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def _thresholds(self) -> Tuple[Tuple[float, float], Tuple[int, int], Tuple[float, float]]:
        cfg = self.config
        r = tuple(float(x) for x in cfg.get("r_thresholds", [30.0, 90.0])[:2])
        f = tuple(int(x) for x in cfg.get("f_thresholds", [5, 2])[:2])
        m = tuple(float(x) for x in cfg.get("m_thresholds", [5000.0, 1500.0])[:2])
        return r, f, m

    def _score_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        recency = _as_float(payload.get("recency_days"), "recency_days")
        frequency_raw = payload.get("frequency")
        if frequency_raw is None or isinstance(frequency_raw, bool):
            raise ValueError("frequency is required and must be numeric")
        try:
            frequency = int(frequency_raw)
        except (TypeError, ValueError):
            raise ValueError(f"frequency must be numeric, got {frequency_raw!r}") from None
        monetary = _as_float(payload.get("monetary"), "monetary")
        r_t, f_t, m_t = self._thresholds()
        return rfm_score(
            recency,
            frequency,
            monetary,
            r_thresholds=r_t,
            f_thresholds=f_t,
            m_thresholds=m_t,
        )

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "score")).lower()
        try:
            if action == "score":
                return _envelope("ok", self._score_payload(payload))
            if action == "batch":
                guests = payload.get("guests")
                if not isinstance(guests, list):
                    return _envelope("refused", error="guests must be a list of profile dicts", detail={"action": action})
                scored: List[Dict[str, Any]] = []
                for idx, guest in enumerate(guests):
                    if not isinstance(guest, dict):
                        return _envelope("refused", error=f"guests[{idx}] is not a dict", detail={"action": action})
                    try:
                        row = self._score_payload(guest)
                    except ValueError as exc:
                        return _envelope("refused", error=str(exc), detail={"index": idx, "action": action})
                    row["guest_id"] = guest.get("guest_id") or guest.get("id")
                    scored.append(row)
                return _envelope("ok", {"segments": scored, "count": len(scored)})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["score", "batch"]})
        except ValueError as exc:
            return _envelope("refused", error=str(exc), detail={"action": action})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
