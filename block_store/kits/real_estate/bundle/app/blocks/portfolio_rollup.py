"""Estate block: portfolio_rollup.

Aggregates a list of property records (``{id, value, status}``) into:

- ``total_value``: sum of property values,
- ``count``: number of records aggregated,
- ``by_status``: per-status ``{count, total_value}`` groupings.

Empty input returns honest zeros (``total_value`` 0, ``count`` 0,
``by_status`` {}). Non-numeric values fail with ``status == "error"`` and
report the offending records in ``detail.invalid_records``. Records without
a status group under ``"unknown"``.

Input may be a bare list or ``{"properties": [...]}`` / ``{"records": [...]}``.

The result envelope keeps the consumer contract:
``{"block_id": "portfolio_rollup", "status": "ok"|"error", "result": ...}``
with ``error``/``detail`` added on failure.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock

_log = logging.getLogger(__name__)

BLOCK_ID = "portfolio_rollup"


def _envelope(
    status: str,
    result: Any = None,
    error: str = "",
    detail: Any = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "block_id": BLOCK_ID,
        "status": status,
        "result": result if result is not None else {},
    }
    if status == "error":
        out["error"] = error
        out["detail"] = detail if detail is not None else {}
    return out


def _coerce_value(value: Any) -> Any:
    """Return a numeric value or None when not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            _log.debug("_coerce_value: not numeric %r: %s", value, exc)
            return None
    return None


def _properties_of(payload: Any) -> Any:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("properties", "records", "items"):
            if key in payload:
                return payload[key]
    return None


def _aggregate(payload: Any) -> Dict[str, Any]:
    properties = _properties_of(payload)
    if properties is None:
        return _envelope(
            "error",
            error="properties must be a list of {id, value, status} records",
            detail={"missing": "properties"},
        )
    if not isinstance(properties, list):
        return _envelope(
            "error",
            error="properties must be a list of {id, value, status} records",
            detail={"received_type": type(properties).__name__},
        )

    total: Any = 0
    count = 0
    by_status: Dict[str, Dict[str, Any]] = {}
    invalid: List[Dict[str, Any]] = []

    for index, prop in enumerate(properties):
        if not isinstance(prop, dict):
            invalid.append({"index": index, "reason": "not an object"})
            continue
        value = _coerce_value(prop.get("value", 0))
        if value is None:
            invalid.append({
                "index": index,
                "id": prop.get("id"),
                "reason": "value is not numeric",
            })
            continue
        status = str(prop.get("status") or "unknown")
        bucket = by_status.setdefault(
            status, {"count": 0, "total_value": 0},
        )
        bucket["count"] += 1
        bucket["total_value"] += value
        total += value
        count += 1

    result = {"total_value": total, "count": count, "by_status": by_status}
    if invalid:
        return _envelope(
            "error",
            error=f"portfolio rollup: {len(invalid)} invalid record(s)",
            detail={"invalid_records": invalid},
            result=result,
        )
    return _envelope("ok", result)


class PortfolioRollupBlock(UniversalBlock):
    """Aggregates property records into total value, count, and per-status groupings."""

    name = "portfolio_rollup"
    version = "1.0.0"
    description = (
        "Aggregates property records ({id, value, status}) into total value, "
        "count, and per-status groupings; empty input yields honest zeros."
    )
    layer = 3
    tags = ["estate", "private_estate_operations", "steward"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {
            "type": "json",
            "accept": None,
            "placeholder": '{"action": "aggregate", "properties": [{"id": "a", "value": 100, "status": "active"}]}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "status", "type": "string", "label": "Status"},
                {"name": "result", "type": "json", "label": "Result"},
                {"name": "error", "type": "string", "label": "Error"},
                {"name": "detail", "type": "json", "label": "Detail"},
            ],
        },
        "quick_actions": [
            {"icon": "📊", "label": "Aggregate Portfolio", "prompt": '{"action": "aggregate", "properties": []}'},
        ],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Execute the portfolio_rollup block."""
        params = params or {}
        payload = input_data if input_data is not None else params
        action = "aggregate"
        if isinstance(payload, dict):
            action = str(payload.get("action", "aggregate")).lower()
        try:
            if action in ("aggregate", "rollup"):
                return _aggregate(payload)
            return _envelope(
                "error", error=f"unknown action: {action}",
                detail={"action": action, "known": ["aggregate"]},
            )
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data: Any, params: Dict = None) -> Dict:
        """Return the standardized ``ok``/``error`` envelope unchanged.

        The estate blocks commit to the consumer contract directly
        (``{"block_id", "status": "ok"|"error", "result", "error", "detail"}``),
        so the base-class ``success``/``error`` remapping must not apply.
        """
        return await self.process(input_data, params)
