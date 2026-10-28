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

# Regional location factors are data, not code: loaded from a JSON file that
# carries its own source record (default app/knowledge/location_factors.json,
# overridable per block via config["location_factors_path"]).
_DEFAULT_LOCATION_FACTORS_PATH = (
    Path(__file__).resolve().parents[1] / "knowledge" / "location_factors.json"
)


def load_location_factors(path: Optional[Path] = None) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Return (factors keyed by normalized location, source record)."""
    path = Path(path) if path else _DEFAULT_LOCATION_FACTORS_PATH
    doc = json.loads(path.read_text(encoding="utf-8"))
    source = doc.get("source")
    if not isinstance(source, dict) or not source.get("origin"):
        raise ValueError(f"{path}: location factors carry no source record")
    table = doc.get("factors")
    if not isinstance(table, dict) or not table:
        raise ValueError(f"{path}: location factors table is missing or empty")
    factors: Dict[str, float] = {}
    for k, v in table.items():
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{path}: location factor for {k!r} is not a number: {v!r}") from None
        if not math.isfinite(f) or f <= 0:
            raise ValueError(f"{path}: location factor for {k!r} must be a finite positive number, got {v!r}")
        factors[_normalize(k)] = f
    return factors, {**source, "path": str(path)}

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


def _location_factor(location: str, factors: Dict[str, float]) -> Optional[float]:
    """The listed factor, or None for an unlisted location (no price is made up)."""
    return factors.get(_normalize(location))


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
        try:
            factors, factor_source = load_location_factors(self.config.get("location_factors_path"))
        except (OSError, ValueError) as exc:
            return {
                "status": "error",
                "action": "lookup",
                "item": item,
                "error": f"location factors unavailable: {type(exc).__name__}: {exc}",
            }
        loc_factor = _location_factor(location, factors)
        if loc_factor is None:
            return {
                "status": "unknown",
                "action": "lookup",
                "item": item,
                "matched_key": key,
                "location": location,
                "location_factor_source": factor_source,
                "error": f"No location factor listed for {location!r}; no adjusted rate is given.",
            }
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
