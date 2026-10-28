"""Historical benchmark block — lightweight, extensible unit-rate source.

Provides plausible, clearly-labeled construction unit rates for common items
(concrete, steel, formwork, etc.) with regional location factors. The block
is intentionally simple: no drifting hardcoded RS-Means snapshot, no ML model.
Rates can be overridden per-item via the learning_engine / record action so
the platform accumulates real project data over time.
"""

import json
import math
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.core.universal_base import UniversalBlock


# Base USD rates for frequently-estimated construction items.
# These are deliberately conservative US-national/industry-average figures;
# the response flags them as estimates and recommends supplier quotes.
_BASE_RATES: Dict[str, Dict[str, Any]] = {
    "concrete": {
        "unit": "m3",
        "base_usd": 150.0,
        "note": "Ready-mix concrete, typical 30 MPa.",
    },
    "ready-mix concrete": {
        "unit": "m3",
        "base_usd": 150.0,
        "note": "Ready-mix concrete, typical 30 MPa.",
    },
    "steel": {
        "unit": "kg",
        "base_usd": 1.0,
        "note": "Reinforcing steel / rebar.",
    },
    "rebar": {
        "unit": "kg",
        "base_usd": 1.0,
        "note": "Reinforcing steel / rebar.",
    },
    "reinforcing steel": {
        "unit": "kg",
        "base_usd": 1.0,
        "note": "Reinforcing steel / rebar.",
    },
    "formwork": {
        "unit": "m2",
        "base_usd": 35.0,
        "note": "Traditional formwork, including labor for erection/stripping.",
    },
    "structural steel": {
        "unit": "kg",
        "base_usd": 2.5,
        "note": "Fabricated structural steel sections.",
    },
    "blockwork": {
        "unit": "m2",
        "base_usd": 45.0,
        "note": "Concrete masonry unit blockwork.",
    },
    "plaster": {
        "unit": "m2",
        "base_usd": 18.0,
        "note": "Internal plaster finish.",
    },
    "paint": {
        "unit": "m2",
        "base_usd": 12.0,
        "note": "Emulsion paint, two coats.",
    },
    "tiles": {
        "unit": "m2",
        "base_usd": 60.0,
        "note": "Ceramic floor/wall tiles including fixing.",
    },
    "excavation": {
        "unit": "m3",
        "base_usd": 15.0,
        "note": "Bulk excavation, machine.",
    },
    "backfill": {
        "unit": "m3",
        "base_usd": 20.0,
        "note": "Imported granular backfill and compaction.",
    },
    "asphalt": {
        "unit": "m2",
        "base_usd": 40.0,
        "note": "Asphalt paving, 50 mm.",
    },
    "earthworks": {
        "unit": "m3",
        "base_usd": 15.0,
        "note": "Bulk earthworks.",
    },
}

# Regional location factors are data, not code. No table ships with the
# block: the earlier inlined figures named no published source and were
# removed (ORDERS 1030Z). A table is supplied via config["location_factors_path"];
# every row must name its own published source, and a row that does not is
# not used (the location then answers no_location_factor).


def load_location_factors(path: Path) -> Tuple[Dict[str, Tuple[float, Dict[str, Any]]], Dict[str, str], Dict[str, Any]]:
    """Return (sourced rows {loc: (factor, row source)}, unsourced {loc: reason}, table source)."""
    path = Path(path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    source = doc.get("source")
    if not isinstance(source, dict) or not source.get("origin"):
        raise ValueError(f"{path}: location factors carry no source record")
    table = doc.get("factors")
    if not isinstance(table, dict) or not table:
        raise ValueError(f"{path}: location factors table is missing or empty")
    sourced: Dict[str, Tuple[float, Dict[str, Any]]] = {}
    unsourced: Dict[str, str] = {}
    for k, row in table.items():
        v = row.get("factor") if isinstance(row, dict) else row
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{path}: location factor for {k!r} is not a number: {v!r}") from None
        if not math.isfinite(f) or f <= 0:
            raise ValueError(f"{path}: location factor for {k!r} must be a finite positive number, got {v!r}")
        row_src = row.get("source") if isinstance(row, dict) else None
        if isinstance(row_src, dict) and str(row_src.get("publication") or "").strip():
            sourced[_normalize(k)] = (f, row_src)
        else:
            unsourced[_normalize(k)] = "its row names no published source"
    return sourced, unsourced, {**source, "path": str(path)}


# Project-type factors.
_PROJECT_TYPE_FACTORS: Dict[str, float] = {
    "general_building": 1.0,
    "building": 1.0,
    "data_center": 1.15,
    "solar_plant": 0.95,
    "wind_farm": 1.05,
    "infrastructure": 0.95,
    "industrial": 1.10,
    "residential": 0.95,
    "commercial": 1.0,
    "healthcare": 1.20,
}


def _normalize(text: str) -> str:
    return (
        (text or "")
        .lower()
        .replace("/", " ")
        .replace("-", " ")
        .replace("_", " ")
        .replace("  ", " ")
        .strip()
    )


def _match_item(name: str) -> Optional[str]:
    norm = _normalize(name)
    # Exact key match first.
    if norm in _BASE_RATES:
        return norm
    # Substring match: item name contains a known key.
    for key in _BASE_RATES:
        if key in norm or norm in key:
            return key
    return None


def _project_factor(project_type: str) -> float:
    return _PROJECT_TYPE_FACTORS.get(_normalize(project_type), 1.0)


class HistoricalBenchmarkBlock(UniversalBlock):
    name = "historical_benchmark"
    version = "1.0.0"
    description = "Lightweight construction unit-rate benchmark source with regional factors"
    layer = 2
    tags = ["construction", "cost", "benchmark", "unit-rates"]
    requires = []

    default_config = {
        "confidence": "medium",
        "source_note": "Fallback static rate book — validate with supplier quotes.",
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        action = params.get("action") or input_data.get("action") if isinstance(input_data, dict) else None

        if action == "record" and isinstance(input_data, dict):
            # Delegate to the learning engine's real correction path — a
            # recorded sample must actually land in the credibility ledger,
            # not return a vacuous success.
            correction = input_data.get("correction_data") or {}
            formula_id = (
                correction.get("formula_id")
                or input_data.get("formula_id")
                or params.get("formula_id")
            )
            predicted = correction.get("predicted", input_data.get("predicted"))
            actual = correction.get("actual", input_data.get("actual"))
            if not formula_id or predicted is None or actual is None:
                return {
                    "status": "error",
                    "action": "record",
                    "error": "record requires correction_data or "
                             "formula_id + predicted + actual",
                }
            try:
                from app.blocks.learning_engine import LearningEngineBlock

                engine = LearningEngineBlock()
                result = await engine.process(
                    {
                        "operation": "record_correction",
                        "correction_data": {
                            "formula_id": formula_id,
                            "predicted": predicted,
                            "actual": actual,
                        },
                    },
                    params,
                )
                return {**result, "action": "record"}
            except Exception as exc:
                return {
                    "status": "error",
                    "action": "record",
                    "error": "learning_engine.record_correction failed: "
                             f"{type(exc).__name__}: {exc}",
                }

        item = params.get("item") or (input_data.get("item") if isinstance(input_data, dict) else "")
        unit = params.get("unit") or (input_data.get("unit") if isinstance(input_data, dict) else "")
        location = params.get("location") or (input_data.get("location") if isinstance(input_data, dict) else "US National Average")
        project_type = params.get("project_type") or (input_data.get("project_type") if isinstance(input_data, dict) else "general_building")

        key = _match_item(item)
        if not key:
            return {
                "status": "error",
                "action": "lookup",
                "item": item,
                "error": f"No benchmark rate available for '{item}'. Provide a supplier quote or add a custom rate.",
            }

        base = _BASE_RATES[key]
        def _no_factor(reason: str, table_source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
            return {
                "status": "no_location_factor",
                "action": "lookup",
                "item": item,
                "matched_key": key,
                "location": location,
                "location_factor_source": table_source,
                "reason": reason,
            }

        table_path = self.config.get("location_factors_path")
        if not table_path:
            return _no_factor("no location factor table is configured (config location_factors_path)")
        try:
            sourced, unsourced, table_source = load_location_factors(table_path)
        except (OSError, ValueError) as exc:
            return {
                "status": "error",
                "action": "lookup",
                "item": item,
                "error": f"location factors unavailable: {type(exc).__name__}: {exc}",
            }
        norm = _normalize(location)
        if norm in unsourced:
            return _no_factor(f"{location!r} is in {table_source['path']} but {unsourced[norm]}", table_source)
        if norm not in sourced:
            return _no_factor(f"{location!r} is not listed in {table_source['path']} ({len(sourced)} sourced rows)", table_source)
        loc_factor, row_source = sourced[norm]
        factor_source = {**table_source, **row_source}
        proj_factor = _project_factor(project_type)
        adjusted = round(base["base_usd"] * loc_factor * proj_factor, 2)

        return {
            "status": "success",
            "action": "lookup",
            "item": item,
            "matched_key": key,
            "unit": unit or base.get("unit"),
            "canonical_unit": base.get("unit"),
            "rates": {
                "base_usd": base["base_usd"],
                "adjusted_usd": adjusted,
            },
            "factors": {
                "location_factor": loc_factor,
                "location_factor_source": factor_source,
                "project_type_factor": proj_factor,
                "location": location,
                "project_type": project_type,
            },
            "note": base.get("note", ""),
            "source_note": self.config.get("source_note"),
            "confidence": self.config.get("confidence"),
        }
