"""Task Listing - deterministic task-marketplace listing logic.

The Airtasker/GESMA core primitive: create and validate a task listing,
geo-qualify it against workers by haversine distance, filter listings by
category/budget/keyword, and suggest a price band per category. Pure Python,
no network, no filesystem. All validation fails closed with an explicit
errors list; no partial listings are ever emitted.

Price bands are embedded defaults (a real kit may load a data file later,
following the agency_commission_engine formula-path pattern); the block
always reports the source of the band it used.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, List, Optional, Tuple

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

CATEGORIES = [
    "cleaning", "delivery", "handyman", "admin", "gardening",
    "moving", "tutoring", "errands", "tech", "other",
]

PRICE_BANDS: Dict[str, Dict[str, Any]] = {
    "cleaning": {"min": 40, "max": 200, "currency": "USD", "unit": "visit", "source": "embedded"},
    "delivery": {"min": 5, "max": 60, "currency": "USD", "unit": "job", "source": "embedded"},
    "handyman": {"min": 50, "max": 400, "currency": "USD", "unit": "job", "source": "embedded"},
    "admin": {"min": 20, "max": 150, "currency": "USD", "unit": "hour", "source": "embedded"},
    "gardening": {"min": 45, "max": 250, "currency": "USD", "unit": "visit", "source": "embedded"},
    "moving": {"min": 80, "max": 600, "currency": "USD", "unit": "job", "source": "embedded"},
    "tutoring": {"min": 25, "max": 120, "currency": "USD", "unit": "hour", "source": "embedded"},
    "errands": {"min": 15, "max": 80, "currency": "USD", "unit": "job", "source": "embedded"},
    "tech": {"min": 30, "max": 250, "currency": "USD", "unit": "hour", "source": "embedded"},
    "other": {"min": 10, "max": 500, "currency": "USD", "unit": "job", "source": "embedded"},
}

MAX_TITLE = 140
MAX_DESCRIPTION = 5000
EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km between two (lat, lng) points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def valid_lat(lat: float) -> bool:
    return isinstance(lat, (int, float)) and -90.0 <= lat <= 90.0


def valid_lng(lng: float) -> bool:
    return isinstance(lng, (int, float)) and -180.0 <= lng <= 180.0


class TaskListingBlock(UniversalBlock):
    """Deterministic task listing creation, geo-qualification and search."""

    name = "task_listing"
    version = "1.0.0"
    description = (
        "Deterministic task-marketplace listing logic: fail-closed creation "
        "and validation, haversine geo-qualification, category/budget/keyword "
        "filtering, and embedded per-category price bands."
    )
    layer = 3
    tags = ["domain", "marketplace", "task", "listing", "geo", "deterministic"]
    requires: List[str] = []
    author = "Cerebrum Team"
    default_config: Dict[str, Any] = {}
    ui_schema = {
        "input": {"type": "json"},
        "output": {"type": "json"},
        "params": [],
        "quick_actions": [],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self.listings: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ api
    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**params, **data}
        operation = merged.get("operation") or merged.get("action") or "create"

        try:
            if operation == "create":
                return self._create(merged)
            if operation == "validate":
                return self._validate(merged)
            if operation == "distance_match":
                return self._distance_match(merged)
            if operation == "filter_search":
                return self._filter_search(merged)
            if operation == "suggest_price_band":
                return self._suggest_price_band(merged)
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc), "operation": operation}

        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": [
                "create", "validate", "distance_match", "filter_search", "suggest_price_band",
            ],
        }

    # -------------------------------------------------------------- helpers
    def _validate_payload(self, data: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append("title: required, non-empty string")
        elif len(title.strip()) > MAX_TITLE:
            errors.append(f"title: exceeds {MAX_TITLE} chars")
        description = data.get("description")
        if description is not None and (not isinstance(description, str) or len(description) > MAX_DESCRIPTION):
            errors.append(f"description: string <= {MAX_DESCRIPTION} chars")
        category = data.get("category")
        if not isinstance(category, str) or category not in CATEGORIES:
            errors.append(f"category: must be one of {CATEGORIES}")
        location = data.get("location") if isinstance(data.get("location"), dict) else {}
        has_coords = "lat" in location or "lng" in location
        if has_coords:
            lat, lng = location.get("lat"), location.get("lng")
            if not valid_lat(lat):
                errors.append("location.lat: float in [-90, 90]")
            if not valid_lng(lng):
                errors.append("location.lng: float in [-180, 180]")
        elif not (isinstance(location.get("address"), str) and location["address"].strip()):
            errors.append("location: provide lat+lng or a non-empty address")
        budget = data.get("budget")
        if budget is not None:
            if not isinstance(budget, dict):
                errors.append("budget: must be an object")
            else:
                bmin, bmax = budget.get("min"), budget.get("max")
                if not isinstance(bmin, (int, float)) or bmin < 0:
                    errors.append("budget.min: number >= 0")
                if not isinstance(bmax, (int, float)) or bmax < bmin:
                    errors.append("budget.max: number >= budget.min")
        return errors

    def _listing_id(self, payload: Dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]

    # ----------------------------------------------------------- operations
    def _create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        payload = data.get("listing") or data.get("payload")
        if not isinstance(payload, dict):
            payload = {
                "title": data.get("title"),
                "description": data.get("description"),
                "category": data.get("category"),
                "location": data.get("location"),
                "budget": data.get("budget"),
            }
        errors = self._validate_payload(payload)
        if errors:
            return {
                "status": "error",
                "error": "validation_failed",
                "errors": errors,
            }
        listing_id = data.get("listing_id") or self._listing_id(payload)
        record = {
            "listing_id": listing_id,
            "title": payload["title"].strip(),
            "description": payload.get("description") or "",
            "category": payload["category"],
            "location": payload["location"],
            "budget": payload.get("budget"),
            "status": "open",
        }
        self.listings[listing_id] = record
        return {
            "status": "success",
            "operation": "create",
            "listing_id": listing_id,
            "listing": record,
        }

    def _validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        payload = data.get("listing") or data.get("payload") or data
        errors = self._validate_payload(payload if isinstance(payload, dict) else {})
        return {
            "status": "success",
            "operation": "validate",
            "valid": not errors,
            "errors": errors,
        }

    def _distance_match(self, data: Dict[str, Any]) -> Dict[str, Any]:
        worker = data.get("worker") if isinstance(data.get("worker"), dict) else {}
        wlat, wlng = worker.get("lat"), worker.get("lng")
        if not valid_lat(wlat) or not valid_lng(wlng):
            return {"status": "error", "error": "worker: valid lat/lng required"}
        try:
            radius_km = float(data.get("radius_km", 25.0))
        except (TypeError, ValueError):
            return {"status": "error", "error": "radius_km: must be a number"}
        if radius_km <= 0:
            return {"status": "error", "error": "radius_km: must be positive"}

        matched: List[Dict[str, Any]] = []
        for listing in self.listings.values():
            loc = listing.get("location") or {}
            lat, lng = loc.get("lat"), loc.get("lng")
            if not valid_lat(lat) or not valid_lng(lng):
                continue
            dist = haversine_km(wlat, wlng, float(lat), float(lng))
            if dist <= radius_km:
                matched.append({"listing_id": listing["listing_id"], "distance_km": round(dist, 3)})
        matched.sort(key=lambda m: m["distance_km"])
        return {
            "status": "success",
            "operation": "distance_match",
            "matched": matched,
            "count": len(matched),
        }

    def _filter_search(self, data: Dict[str, Any]) -> Dict[str, Any]:
        category = data.get("category")
        keyword = (data.get("keyword") or "").strip().lower()
        budget_max = data.get("budget_max")
        status = data.get("status") or "open"
        results: List[Dict[str, Any]] = []
        for listing in self.listings.values():
            if listing.get("status") != status:
                continue
            if category and listing.get("category") != category:
                continue
            if keyword and keyword not in listing.get("title", "").lower() and keyword not in listing.get("description", "").lower():
                continue
            if budget_max is not None:
                budget = listing.get("budget")
                if not budget or budget.get("min", float("inf")) > budget_max:
                    continue
            results.append(listing)
        return {
            "status": "success",
            "operation": "filter_search",
            "results": results,
            "count": len(results),
        }

    def _suggest_price_band(self, data: Dict[str, Any]) -> Dict[str, Any]:
        category = data.get("category")
        if category not in CATEGORIES:
            return {
                "status": "error",
                "error": f"category: must be one of {CATEGORIES}",
            }
        band = dict(PRICE_BANDS[category])
        duration = data.get("duration_hours")
        if duration is not None and band.get("unit") in ("hour", "visit"):
            try:
                hours = float(duration)
            except (TypeError, ValueError):
                return {"status": "error", "error": "duration_hours: must be a number"}
            if hours > 0:
                band["min"] = round(band["min"] * hours, 2)
                band["max"] = round(band["max"] * hours, 2)
        return {
            "status": "success",
            "operation": "suggest_price_band",
            "category": category,
            "band": band,
        }
