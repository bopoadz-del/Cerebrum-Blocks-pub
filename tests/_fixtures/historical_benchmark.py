"""Historical Benchmark Block — RS Means-style unit cost lookups and market ranges.

The block has two backends:

* **File-backed** (default): the original behaviour. Demo rates plus optional
  JSON files referenced by ``BENCHMARK_RATES_PATH`` / ``BENCHMARK_FACTORS_PATH``.
* **Postgres** (opt-in): activated when ``DATABASE_URL`` is set *and* ``asyncpg``
  is importable. Reads the ``historical_benchmark`` and ``location_factor``
  tables produced by ``migrations/001_historical_benchmark.sql``.

Public-method shapes are unchanged. The Postgres backend never grows the API —
it only sources the underlying numbers. Any failure (driver missing, connection
refused, table missing, empty table) falls back transparently to the file-backed
store for that single call so the block keeps working in degraded mode.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from app.core.universal_base import UniversalBlock

try:  # pragma: no cover - optional dependency
    import asyncpg  # type: ignore
except Exception:  # noqa: BLE001 - asyncpg is optional
    asyncpg = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


# Module-level pool + lock so multiple block instances share a single asyncpg
# pool. Lazily initialised on first use; recreated if a previous attempt failed.
_pg_pool: Optional[Any] = None
_pg_pool_lock: Optional[asyncio.Lock] = None
_pg_pool_failed: bool = False


def _get_pool_lock() -> asyncio.Lock:
    """Return a per-event-loop lock guarding pool creation."""
    global _pg_pool_lock
    if _pg_pool_lock is None:
        _pg_pool_lock = asyncio.Lock()
    return _pg_pool_lock


async def _get_or_create_pool(dsn: str) -> Optional[Any]:
    """Return a shared asyncpg pool, creating it on first call.

    Returns ``None`` if asyncpg is unavailable or pool creation fails. The
    failure flag is sticky so we don't hammer a broken DB on every call.
    """
    global _pg_pool, _pg_pool_failed
    if asyncpg is None:
        return None
    if _pg_pool_failed:
        return None
    if _pg_pool is not None:
        return _pg_pool
    async with _get_pool_lock():
        if _pg_pool is not None:
            return _pg_pool
        try:
            _pg_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
            return _pg_pool
        except Exception as exc:  # noqa: BLE001 - any pool error degrades to file
            logger.warning("historical_benchmark: pg pool creation failed: %s", exc)
            _pg_pool_failed = True
            return None


async def _reset_pool_for_tests() -> None:
    """Test helper — drop the cached pool so tests can re-monkeypatch."""
    global _pg_pool, _pg_pool_lock, _pg_pool_failed
    if _pg_pool is not None:
        try:
            await _pg_pool.close()
        except Exception:  # noqa: BLE001
            pass
    _pg_pool = None
    _pg_pool_lock = None
    _pg_pool_failed = False


class _PostgresStore:
    """Async accessor for the Postgres-backed benchmark tables.

    All methods raise :class:`RuntimeError` when no pool is available; the
    block's dispatchers catch that and fall back to the file path.
    """

    def __init__(self, dsn: str):
        self._dsn = dsn

    async def _pool(self) -> Any:
        pool = await _get_or_create_pool(self._dsn)
        if pool is None:
            raise RuntimeError("postgres pool unavailable")
        return pool

    async def is_seeded(self) -> bool:
        """``True`` when ``historical_benchmark`` has at least one row."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 AS x FROM historical_benchmark LIMIT 1"
            )
            return row is not None

    async def lookup(
        self, item: str, unit: str, location: str
    ) -> Optional[Dict[str, Any]]:
        """Best-effort exact / fuzzy lookup.

        Tries (item, unit, location) first, then (item, unit) ignoring location,
        then a ``LIKE`` match. Returns ``None`` when nothing matches.

        Returned dict shape mirrors the file-backed ``rate_data`` contract used
        by ``_lookup`` (``base`` / ``low`` / ``high`` / ``unit`` / ``trade``)
        plus DB-only fields ``avg_cost`` / ``std_dev`` / ``sample_size`` /
        ``source``.
        """
        pool = await self._pool()
        loc = (location or "").lower().strip() or None
        async with pool.acquire() as conn:
            row = None
            if loc:
                row = await conn.fetchrow(
                    """
                    SELECT item_name, unit, avg_cost, std_dev, sample_size,
                           location, source
                      FROM historical_benchmark
                     WHERE lower(item_name) = lower($1)
                       AND lower(unit)      = lower($2)
                       AND lower(location)  = lower($3)
                     LIMIT 1
                    """,
                    item, unit, loc,
                )
            if row is None:
                row = await conn.fetchrow(
                    """
                    SELECT item_name, unit, avg_cost, std_dev, sample_size,
                           location, source
                      FROM historical_benchmark
                     WHERE lower(item_name) = lower($1)
                       AND lower(unit)      = lower($2)
                     ORDER BY (location IS NULL) DESC, sample_size DESC
                     LIMIT 1
                    """,
                    item, unit,
                )
            if row is None:
                row = await conn.fetchrow(
                    """
                    SELECT item_name, unit, avg_cost, std_dev, sample_size,
                           location, source
                      FROM historical_benchmark
                     WHERE lower(item_name) LIKE lower($1)
                     ORDER BY sample_size DESC
                     LIMIT 1
                    """,
                    f"%{item}%",
                )
        if row is None:
            return None
        avg = float(row["avg_cost"])
        sd = float(row["std_dev"] or 0.0)
        return {
            "key": row["item_name"],
            "unit": row["unit"],
            "trade": row["source"] or "benchmark",
            "base": avg,
            "low": round(max(0.0, avg - sd), 4),
            "high": round(avg + sd, 4),
            "avg_cost": avg,
            "std_dev": sd,
            "sample_size": int(row["sample_size"] or 0),
            "source": row["source"],
            "location": row["location"],
        }

    async def catalogue(self) -> List[Dict[str, Any]]:
        """Return every benchmark row as a list of ``rate_data``-shaped dicts."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT item_name, unit, avg_cost, std_dev, sample_size,
                       location, source
                  FROM historical_benchmark
                 ORDER BY item_name, location
                """
            )
        out: List[Dict[str, Any]] = []
        for r in rows:
            avg = float(r["avg_cost"])
            sd = float(r["std_dev"] or 0.0)
            out.append({
                "key": r["item_name"],
                "unit": r["unit"],
                "trade": r["source"] or "benchmark",
                "base_rate_usd": avg,
                "range": f"{round(max(0.0, avg - sd), 2)} – {round(avg + sd, 2)}",
                "location": r["location"],
                "sample_size": int(r["sample_size"] or 0),
            })
        return out

    async def location_factor(self, location: str) -> Optional[float]:
        """Return the regional cost factor for *location* (case-insensitive)."""
        pool = await self._pool()
        loc = (location or "").lower().strip()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT factor FROM location_factor WHERE lower(location) = $1",
                loc,
            )
            if row is not None:
                return float(row["factor"])
            # Soft match: substring either direction (mirrors file fallback).
            row = await conn.fetchrow(
                """
                SELECT factor FROM location_factor
                 WHERE lower(location) LIKE $1
                    OR $2 LIKE '%' || lower(location) || '%'
                 LIMIT 1
                """,
                f"%{loc}%", loc,
            )
        return float(row["factor"]) if row is not None else None


class HistoricalBenchmarkBlock(UniversalBlock):
    name = "historical_benchmark"
    version = "1.1"
    description = "RS Means-style benchmark unit costs, cost ranges, and market data for construction items"
    layer = 2
    tags = ["construction", "cost", "benchmark", "rsmeans", "aec"]

    ui_schema = {
        "input": {
            "type": "json",
            "accept": None,
            "placeholder": "Item description, unit, location, project type",
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "unit_cost", "type": "number", "label": "Unit cost"},
                {"name": "range", "type": "json", "label": "Cost range"},
                {"name": "location_factor", "type": "number", "label": "Location factor"},
            ],
        },
        "params": [
            {"name": "item", "type": "text", "label": "Item description", "default": ""},
            {"name": "unit", "type": "text", "label": "Unit (m2, m3, kg, ea…)", "default": ""},
            {"name": "location", "type": "text", "label": "Location / city", "default": ""},
            {"name": "project_type", "type": "text", "label": "Project type", "default": ""},
        ],
        "quick_actions": [
            {"icon": "💰", "label": "Benchmark cost", "prompt": "Look up benchmark unit cost for this item"},
        ],
    }

    default_config = {
        "rates_env": "BENCHMARK_RATES_PATH",
        "factors_env": "BENCHMARK_FACTORS_PATH",
        "database_url_env": "DATABASE_URL",
    }

    # In-code defaults that mirror migrations/001_historical_benchmark.sql so a
    # fresh boot without DB still produces sensible location adjustments.
    _DEFAULT_LOCATION_FACTORS: Dict[str, float] = {
        "us_national_average": 1.00,
        "us national average": 1.00,
        "riyadh": 0.85,
        "jeddah": 0.83,
        "dubai": 0.95,
        "london": 1.45,
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self._rates: Dict[str, Dict] = {}
        self._location_factors: Dict[str, float] = {}
        self._project_factors: Dict[str, float] = {}
        self._pg_store: Optional[_PostgresStore] = None
        self._pg_active: bool = False
        self._load_data()
        self._init_pg_backend()

    # ------------------------------------------------------------------
    # Backend selection
    # ------------------------------------------------------------------

    def _init_pg_backend(self) -> None:
        """Decide whether to use Postgres based on env + driver availability."""
        dsn_env = self.config.get("database_url_env", "DATABASE_URL")
        dsn = os.environ.get(dsn_env, "").strip()
        if not dsn:
            logger.info("historical_benchmark: using file backend (no %s)", dsn_env)
            return
        if asyncpg is None:
            logger.info(
                "historical_benchmark: %s set but asyncpg not installed; "
                "using file backend",
                dsn_env,
            )
            return
        self._pg_store = _PostgresStore(dsn)
        self._pg_active = True
        logger.info("historical_benchmark: using Postgres backend")

    def _load_data(self):
        """Load benchmark data from external files or environment variables."""
        rates_path = os.environ.get(
            self.config.get("rates_env", "BENCHMARK_RATES_PATH"), ""
        )
        factors_path = os.environ.get(
            self.config.get("factors_env", "BENCHMARK_FACTORS_PATH"), ""
        )

        if rates_path and os.path.exists(rates_path):
            try:
                with open(rates_path, "r") as f:
                    self._rates = json.load(f)
            except Exception:
                pass

        if factors_path and os.path.exists(factors_path):
            try:
                with open(factors_path, "r") as f:
                    factors = json.load(f)
                    self._location_factors = factors.get("location_factors", {})
                    self._project_factors = factors.get("project_factors", {})
            except Exception:
                pass

        # Default demo rates so the block works out-of-the-box
        if not self._rates:
            self._rates = {
                "concrete": {"unit": "m3", "rate_usd": 150, "location": "US National Average", "project_type": "general_building"},
                "rebar": {"unit": "kg", "rate_usd": 1.8, "location": "US National Average", "project_type": "general_building"},
                "structural_steel": {"unit": "kg", "rate_usd": 2.5, "location": "US National Average", "project_type": "general_building"},
                "formwork": {"unit": "m2", "rate_usd": 45, "location": "US National Average", "project_type": "general_building"},
                "excavation": {"unit": "m3", "rate_usd": 25, "location": "US National Average", "project_type": "general_building"},
            }

        # Seed default location factors when nothing was supplied via file —
        # keeps parity with the migration seed.
        if not self._location_factors:
            self._location_factors = dict(self._DEFAULT_LOCATION_FACTORS)

    # ------------------------------------------------------------------
    # Process entry point
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}

        action = params.get("action", data.get("action", "lookup"))

        # Allow inline injection of benchmark data for real computation
        inline_rates = data.get("rates") or params.get("rates")
        inline_loc_factors = data.get("location_factors") or params.get("location_factors")
        inline_proj_factors = data.get("project_factors") or params.get("project_factors")

        if inline_rates:
            self._rates.update(inline_rates)
        if inline_loc_factors:
            self._location_factors.update(inline_loc_factors)
        if inline_proj_factors:
            self._project_factors.update(inline_proj_factors)

        if action == "lookup":
            return await self._dispatch_lookup(data, params)
        if action == "batch":
            return await self._dispatch_batch(data, params)
        if action == "location_factors":
            return {"status": "success", "location_factors": self._location_factors}
        if action == "catalogue":
            return await self._dispatch_catalogue(params)

        return await self._dispatch_lookup(data, params)

    # ------------------------------------------------------------------
    # Async dispatchers — try Postgres, fall back to file path on any
    # error, on empty table, or when the backend is inactive.
    # ------------------------------------------------------------------

    async def _dispatch_lookup(self, data: Dict, params: Dict) -> Dict:
        if self._pg_active and self._pg_store is not None:
            try:
                if not await self._pg_store.is_seeded():
                    logger.info(
                        "historical_benchmark: pg table empty, using file backend"
                    )
                else:
                    pg_result = await self._pg_lookup(data, params)
                    if pg_result is not None:
                        return pg_result
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "historical_benchmark: pg lookup failed (%s); "
                    "falling back to file backend",
                    exc,
                )
        return self._lookup(data, params)

    async def _dispatch_batch(self, data: Dict, params: Dict) -> Dict:
        items: List[Dict] = params.get("items") or data.get("items") or []
        location = (params.get("location") or data.get("location", "us national average")).lower()
        project_type = (params.get("project_type") or data.get("project_type", "general_building")).lower()

        results = []
        total = 0.0
        for item in items:
            sub_params = {
                "location": location,
                "project_type": project_type,
                "item": item.get("item", item.get("description", "")),
                "unit": item.get("unit", ""),
            }
            result = await self._dispatch_lookup({**data, **item}, sub_params)
            qty = float(item.get("quantity", 1))
            if result.get("status") == "success":
                line_total = round(result["rates"]["adjusted_usd"] * qty, 2)
                result["quantity"] = qty
                result["line_total"] = line_total
                total += line_total
            results.append(result)

        return {
            "status": "success",
            "action": "batch_lookup",
            "items_requested": len(items),
            "items_matched": len([r for r in results if r.get("status") == "success"]),
            "total_cost_usd": round(total, 2),
            "results": results,
        }

    async def _dispatch_catalogue(self, params: Dict) -> Dict:
        if self._pg_active and self._pg_store is not None:
            try:
                pg_items = await self._pg_store.catalogue()
                if pg_items:
                    trade_filter = (params.get("trade", "") or "").lower()
                    if trade_filter:
                        pg_items = [
                            it for it in pg_items
                            if trade_filter in (it.get("trade") or "").lower()
                        ]
                    return {
                        "status": "success",
                        "action": "catalogue",
                        "total_items": len(pg_items),
                        "items": pg_items,
                        "source": "postgres",
                    }
                logger.info(
                    "historical_benchmark: pg catalogue empty, using file backend"
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "historical_benchmark: pg catalogue failed (%s); "
                    "falling back to file backend",
                    exc,
                )
        return self._get_catalogue(params)

    # ------------------------------------------------------------------
    # Postgres-backed lookup. Returns the same dict shape as ``_lookup``;
    # returns ``None`` to signal "no match" so the dispatcher can decide
    # whether to fall back.
    # ------------------------------------------------------------------

    async def _pg_lookup(self, data: Dict, params: Dict) -> Optional[Dict]:
        if self._pg_store is None:
            return None
        item = params.get("item") or data.get("item") or data.get("description") or data.get("text") or data.get("input", "")
        unit = (params.get("unit") or data.get("unit", "")).lower()
        location = (params.get("location") or data.get("location", "us national average")).lower()
        project_type = (params.get("project_type") or data.get("project_type", "general_building")).lower()

        rate_data = await self._pg_store.lookup(item, unit, location)
        if rate_data is None:
            # Try the file matcher's keyed names in case caller passed natural
            # language ("structural steel") that maps to a benchmark key
            # ("structural_steel_kg" -> stripped to "structural_steel" etc.).
            key, _ = self._find_best_match(item, unit)
            if key:
                stripped = key.rsplit("_", 1)[0] if "_" in key else key
                for candidate in (key, stripped, key.replace("_", " ")):
                    rate_data = await self._pg_store.lookup(candidate, unit, location)
                    if rate_data is not None:
                        break
        if rate_data is None:
            return None

        loc_factor = await self._lookup_location_factor_async(location)
        proj_factor = self._project_factors.get(project_type, 1.05)

        base = float(rate_data["base"])
        adjusted = round(base * loc_factor * proj_factor, 2)

        return {
            "status": "success",
            "item": item,
            "matched_key": rate_data.get("key"),
            "unit": rate_data["unit"],
            "trade": rate_data["trade"],
            "rates": {
                "base_usd": base,
                "low_usd": round(rate_data["low"] * loc_factor * proj_factor, 2),
                "high_usd": round(rate_data["high"] * loc_factor * proj_factor, 2),
                "adjusted_usd": adjusted,
            },
            "factors": {
                "location": location,
                "location_factor": loc_factor,
                "project_type": project_type,
                "project_factor": proj_factor,
            },
            "stats": {
                "avg_cost": rate_data.get("avg_cost"),
                "std_dev": rate_data.get("std_dev"),
                "sample_size": rate_data.get("sample_size"),
            },
            "confidence": "high" if rate_data.get("sample_size", 0) >= 30 else "medium",
            "source": rate_data.get("source") or "postgres benchmark database",
        }

    async def _lookup_location_factor_async(self, location: str) -> float:
        """Postgres-aware location factor lookup with file fallback."""
        if self._pg_active and self._pg_store is not None:
            try:
                pg_factor = await self._pg_store.location_factor(location)
                if pg_factor is not None:
                    return pg_factor
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "historical_benchmark: pg location_factor failed (%s); "
                    "falling back to file backend",
                    exc,
                )
        return self._get_location_factor(location)

    # ------------------------------------------------------------------
    # File-backed implementations — unchanged behaviour. Used directly when
    # the Postgres backend is disabled, and as a fallback otherwise.
    # ------------------------------------------------------------------

    def _lookup(self, data: Dict, params: Dict) -> Dict:
        item = params.get("item") or data.get("item") or data.get("description") or data.get("text") or data.get("input", "")
        unit = (params.get("unit") or data.get("unit", "")).lower()
        location = (params.get("location") or data.get("location", "us national average")).lower()
        project_type = (params.get("project_type") or data.get("project_type", "general_building")).lower()

        if not self._rates:
            return {
                "status": "error",
                "error": "No benchmark data loaded. Provide rates via inline params, environment variable, or file.",
            }

        loc_factor = self._get_location_factor(location)
        proj_factor = self._project_factors.get(project_type, 1.05)

        rate_key, rate_data = self._find_best_match(item, unit)

        if not rate_data:
            return {
                "status": "not_found",
                "item": item,
                "message": f"No benchmark found for '{item}' ({unit}). Check catalogue for available items.",
            }

        base = rate_data["base"]
        adjusted = round(base * loc_factor * proj_factor, 2)

        return {
            "status": "success",
            "item": item,
            "matched_key": rate_key,
            "unit": rate_data["unit"],
            "trade": rate_data["trade"],
            "rates": {
                "base_usd": base,
                "low_usd": round(rate_data["low"] * loc_factor * proj_factor, 2),
                "high_usd": round(rate_data["high"] * loc_factor * proj_factor, 2),
                "adjusted_usd": adjusted,
            },
            "factors": {
                "location": location,
                "location_factor": loc_factor,
                "project_type": project_type,
                "project_factor": proj_factor,
            },
            "confidence": "high" if rate_key in item.lower().replace(" ", "_") else "medium",
            "source": "external benchmark database",
        }

    def _batch_lookup(self, data: Dict, params: Dict) -> Dict:
        items: List[Dict] = params.get("items") or data.get("items") or []
        location = (params.get("location") or data.get("location", "us national average")).lower()
        project_type = (params.get("project_type") or data.get("project_type", "general_building")).lower()

        results = []
        total = 0.0
        for item in items:
            result = self._lookup(
                {**data, **item},
                {"location": location, "project_type": project_type,
                 "item": item.get("item", item.get("description", "")),
                 "unit": item.get("unit", "")},
            )
            qty = float(item.get("quantity", 1))
            if result.get("status") == "success":
                line_total = round(result["rates"]["adjusted_usd"] * qty, 2)
                result["quantity"] = qty
                result["line_total"] = line_total
                total += line_total
            results.append(result)

        return {
            "status": "success",
            "action": "batch_lookup",
            "items_requested": len(items),
            "items_matched": len([r for r in results if r.get("status") == "success"]),
            "total_cost_usd": round(total, 2),
            "results": results,
        }

    def _get_catalogue(self, params: Dict) -> Dict:
        trade_filter = params.get("trade", "").lower()
        items = []
        for key, data in self._rates.items():
            trade = data.get("trade", "")
            if trade_filter and trade_filter not in trade.lower():
                continue
            items.append({
                "key": key,
                "unit": data.get("unit"),
                "trade": trade,
                "base_rate_usd": data.get("base", data.get("rate_usd")),
                "range": (
                    f"{data['low']} – {data['high']}"
                    if "low" in data and "high" in data
                    else f"{data.get('rate_usd', 0)} – {data.get('rate_usd', 0)}"
                ),
            })
        return {
            "status": "success",
            "action": "catalogue",
            "total_items": len(items),
            "items": items,
        }

    def _find_best_match(self, item: str, unit: str) -> Tuple[str, Optional[Dict]]:
        n = item.lower()
        u = unit.lower()

        # Exact keyword matching in priority order
        if "curtain wall" in n or "curtain_wall" in n:
            return "curtain_wall_m2", self._rates.get("curtain_wall_m2")
        if "cladding" in n:
            return "cladding_m2", self._rates.get("cladding_m2")
        if "glazing" in n or "glass" in n:
            return "glazing_standard_m2", self._rates.get("glazing_standard_m2")
        if "lift" in n or "elevator" in n:
            return "lift_passenger_ea", self._rates.get("lift_passenger_ea")
        if "structural steel" in n or ("steel" in n and "kg" in u):
            return "structural_steel_kg", self._rates.get("structural_steel_kg")
        if "rebar" in n or "reinforcement" in n:
            return "rebar_kg", self._rates.get("rebar_kg")
        if "c40" in n or ("concrete" in n and "40" in n):
            return "concrete_c40_m3", self._rates.get("concrete_c40_m3")
        if "c30" in n or ("concrete" in n and "30" in n):
            return "concrete_c30_m3", self._rates.get("concrete_c30_m3")
        if "concrete" in n and "m3" in u:
            return "concrete_c25_m3", self._rates.get("concrete_c25_m3")
        if "soffit" in n or ("formwork" in n and "soffit" in n):
            return "formwork_soffit_m2", self._rates.get("formwork_soffit_m2")
        if "formwork" in n or "shuttering" in n:
            return "formwork_standard_m2", self._rates.get("formwork_standard_m2")
        if "pil" in n:
            return "piling_lm", self._rates.get("piling_lm")
        if "excavat" in n:
            return "excavation_m3", self._rates.get("excavation_m3")
        if "brick" in n:
            return "brickwork_m2", self._rates.get("brickwork_m2")
        if "block" in n and "m2" in u:
            return "blockwork_m2", self._rates.get("blockwork_m2")
        if "waterproof" in n or "membrane" in n:
            return "waterproofing_m2", self._rates.get("waterproofing_m2")
        if "roof" in n:
            return "roofing_flat_m2", self._rates.get("roofing_flat_m2")
        if "suspended ceiling" in n or "false ceiling" in n:
            return "suspended_ceiling_m2", self._rates.get("suspended_ceiling_m2")
        if "drylining" in n or "drywall" in n:
            return "drylining_m2", self._rates.get("drylining_m2")
        if "plaster" in n:
            return "plaster_m2", self._rates.get("plaster_m2")
        if "premium tile" in n or "marble" in n or "stone tile" in n:
            return "tiling_premium_m2", self._rates.get("tiling_premium_m2")
        if "tile" in n or "tiling" in n:
            return "tiling_standard_m2", self._rates.get("tiling_standard_m2")
        if "floor" in n and "screed" in n:
            return "flooring_screed_m2", self._rates.get("flooring_screed_m2")
        if "paint" in n:
            return "painting_m2", self._rates.get("painting_m2")
        if "insulation" in n:
            return "insulation_thermal_m2", self._rates.get("insulation_thermal_m2")
        if "hvac" in n or "mechanical" in n or "air" in n:
            return "hvac_medium_m2", self._rates.get("hvac_medium_m2")
        if "fire" in n and "protection" in n:
            return "fire_protection_m2", self._rates.get("fire_protection_m2")
        if "electrical" in n or "lighting" in n:
            return "electrical_standard_m2", self._rates.get("electrical_standard_m2")
        if "plumbing" in n or "sanitary" in n:
            return "plumbing_standard_m2", self._rates.get("plumbing_standard_m2")
        if "external door" in n:
            return "door_external_ea", self._rates.get("door_external_ea")
        if "door" in n:
            return "door_internal_ea", self._rates.get("door_internal_ea")
        if "window" in n:
            return "window_standard_ea", self._rates.get("window_standard_ea")
        if "scaffold" in n:
            return "scaffold_m2", self._rates.get("scaffold_m2")

        return "", None

    def _get_location_factor(self, location: str) -> float:
        loc = location.lower().strip()
        if loc in self._location_factors:
            return self._location_factors[loc]
        for key, factor in self._location_factors.items():
            if key in loc or loc in key:
                return factor
        return 1.0
