"""Product formulas — shipped by the Console Floor pack.

This is the formulas surface a factory-emitted product serves. It is a
FLOOR, not a cage: a product may override this file with its own formulas.

Deterministic built-ins are evaluated here (platform definitions, never
fabricated); anything else delegates to the store's formula_executor_v2
block so the product keeps the full formula capability.
"""
from __future__ import annotations

from typing import Any, Dict

_BUILTIN_FIELDS = {
    "area_rectangle": (("width", "height"), lambda v: v["width"] * v["height"], "m2"),
    "volume_box": (("length", "width", "height"), lambda v: v["length"] * v["width"] * v["height"], "m3"),
}


def _authority(verdict: str, source: str) -> Dict[str, Any]:
    return {"verdict": verdict, "source": source}


async def evaluate(formula_id: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a formula. Built-ins carry a grounded platform-definition
    verdict; delegated formulas report the block's result with an honest
    delegation label."""
    variables = variables or {}
    if formula_id in _BUILTIN_FIELDS:
        fields, fn, unit = _BUILTIN_FIELDS[formula_id]
        missing = [f for f in fields if f not in variables]
        if missing:
            return {
                "formula_id": formula_id,
                "status": "error",
                "error": f"missing variables: {', '.join(missing)}",
                "authority": _authority("blocked", "platform_definition"),
            }
        try:
            value = fn({k: float(variables[k]) for k in fields})
        except (TypeError, ValueError) as exc:
            return {
                "formula_id": formula_id,
                "status": "error",
                "error": f"non-numeric variable: {exc}",
                "authority": _authority("blocked", "platform_definition"),
            }
        return {
            "formula_id": formula_id,
            "status": "success",
            "value": value,
            "unit": unit,
            "authority": _authority("grounded", "platform_definition"),
        }

    from app.blocks import get_block

    block = get_block("formula_executor_v2")
    if block is None:
        return {
            "formula_id": formula_id,
            "status": "error",
            "error": "formula_executor_v2 unavailable",
            "authority": _authority("blocked", "runtime"),
        }
    result = await block.process(variables, {"formula_id": formula_id})
    result["authority"] = _authority("delegated", "block:formula_executor_v2")
    return result
