"""Vendor Catalog - deterministic food-delivery catalog and search.

The delivery marketplace's catalog primitive: vendor registration with
service areas, item management with exact Decimal pricing, availability
toggles, keyword/category/budget search, and status snapshots. Pure
decision block: no network, no filesystem. Inactive vendors cannot list
or search; every refusal names the reason.

Prices are Decimal and never float; duplicate ids are refused; category
values are a closed set so cross-block filtering stays consistent.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

CENT = Decimal("0.01")

CATEGORIES = ("food", "grocery", "pharmacy", "retail", "other")


def money(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid money value: {value!r}")


class VendorCatalogBlock(UniversalBlock):
    """Deterministic vendor/item catalog with search and availability."""

    name = "vendor_catalog"
    version = "1.0.0"
    description = (
        "Deterministic delivery catalog: vendor registration with service "
        "areas, item management with exact Decimal pricing, availability "
        "toggles, keyword/category/budget search, and status snapshots. "
        "Inactive vendors cannot list items."
    )
    layer = 3
    tags = ["domain", "marketplace", "catalog", "delivery", "deterministic"]
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
        # vendor_id -> record
        self.vendors: Dict[str, Dict[str, Any]] = {}
        # item_id -> record
        self.items: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ api
    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**params, **data}
        operation = merged.get("operation") or merged.get("action") or "register_vendor"

        try:
            if operation == "register_vendor":
                return self._register_vendor(merged)
            if operation == "add_item":
                return self._add_item(merged)
            if operation == "list_items":
                return self._list_items(merged)
            if operation == "search_items":
                return self._search_items(merged)
            if operation == "set_availability":
                return self._set_availability(merged)
            if operation == "status":
                return self._status(merged)
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc), "operation": operation}

        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": [
                "register_vendor", "add_item", "list_items",
                "search_items", "set_availability", "status",
            ],
        }

    # -------------------------------------------------------------- helpers
    def _require(self, data: Dict[str, Any], keys: List[str]) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                return key
        return None

    # ----------------------------------------------------------- operations
    def _register_vendor(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["vendor_id", "name"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        categories = data.get("categories") or []
        if not isinstance(categories, list) or not categories:
            return {"status": "error", "error": "categories: non-empty list required"}
        if any(c not in CATEGORIES for c in categories):
            return {
                "status": "error",
                "error": f"categories: closed set {list(CATEGORIES)}",
            }
        try:
            radius = float(data.get("service_radius_km", 5.0))
        except (TypeError, ValueError):
            return {"status": "error", "error": "service_radius_km: must be a number"}
        if radius <= 0:
            return {"status": "error", "error": "service_radius_km: must be positive"}

        existing = self.vendors.get(data["vendor_id"])
        if existing is not None:
            return {**existing["public"], "idempotent": True}
        record = {
            "vendor_id": data["vendor_id"],
            "name": data["name"],
            "categories": list(categories),
            "service_radius_km": radius,
            "active": bool(data.get("active", True)),
        }
        public = {
            "status": "success",
            "operation": "register_vendor",
            "vendor_id": data["vendor_id"],
            "name": data["name"],
            "categories": record["categories"],
        }
        record["public"] = public
        self.vendors[data["vendor_id"]] = record
        return public

    def _add_item(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["vendor_id", "item_id", "name", "price"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        vendor = self.vendors.get(data["vendor_id"])
        if vendor is None:
            return {"status": "error", "error": "vendor_not_found"}
        if not vendor["active"]:
            return {"status": "error", "error": "vendor_inactive"}
        try:
            price = money(data["price"])
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc)}
        if price <= 0:
            return {"status": "error", "error": "price: must be positive"}
        category = data.get("category") or "other"
        if category not in CATEGORIES:
            return {"status": "error", "error": f"category: closed set {list(CATEGORIES)}"}

        existing = self.items.get(data["item_id"])
        if existing is not None:
            return {**existing["public"], "idempotent": True}
        record = {
            "item_id": data["item_id"],
            "vendor_id": data["vendor_id"],
            "name": data["name"],
            "price": price,
            "category": category,
            "available": bool(data.get("available", True)),
        }
        public = {
            "status": "success",
            "operation": "add_item",
            "item_id": data["item_id"],
            "vendor_id": data["vendor_id"],
            "price": str(price),
        }
        record["public"] = public
        self.items[data["item_id"]] = record
        return public

    def _list_items(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["vendor_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        vendor = self.vendors.get(data["vendor_id"])
        if vendor is None:
            return {"status": "error", "error": "vendor_not_found"}
        items = [i for i in self.items.values() if i["vendor_id"] == data["vendor_id"]]
        return {
            "status": "success",
            "operation": "list_items",
            "vendor_id": data["vendor_id"],
            "items": items,
            "count": len(items),
        }

    def _search_items(self, data: Dict[str, Any]) -> Dict[str, Any]:
        keyword = (data.get("keyword") or "").strip().lower()
        category = data.get("category")
        if category is not None and category not in CATEGORIES:
            return {"status": "error", "error": f"category: closed set {list(CATEGORIES)}"}
        price_max = data.get("price_max")
        if price_max is not None:
            try:
                price_max = money(price_max)
            except ValueError as exc:
                return {"status": "error", "error": str(exc), "error_kind": error_kind(exc)}
        results: List[Dict[str, Any]] = []
        for item in self.items.values():
            vendor = self.vendors.get(item["vendor_id"])
            if vendor is None or not vendor["active"] or not item["available"]:
                continue
            if category and item["category"] != category:
                continue
            if keyword and keyword not in item["name"].lower():
                continue
            if price_max is not None and item["price"] > price_max:
                continue
            results.append(item)
        return {
            "status": "success",
            "operation": "search_items",
            "results": results,
            "count": len(results),
        }

    def _set_availability(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["item_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        item = self.items.get(data["item_id"])
        if item is None:
            return {"status": "error", "error": "item_not_found"}
        item["available"] = bool(data.get("available", True))
        return {
            "status": "success",
            "operation": "set_availability",
            "item_id": data["item_id"],
            "available": item["available"],
        }

    def _status(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["vendor_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        vendor = self.vendors.get(data["vendor_id"])
        if vendor is None:
            return {"status": "error", "error": "vendor_not_found"}
        item_count = sum(
            1 for i in self.items.values() if i["vendor_id"] == data["vendor_id"]
        )
        available_count = sum(
            1 for i in self.items.values()
            if i["vendor_id"] == data["vendor_id"] and i["available"]
        )
        return {
            "status": "success",
            "operation": "status",
            "vendor_id": data["vendor_id"],
            "name": vendor["name"],
            "active": vendor["active"],
            "categories": vendor["categories"],
            "service_radius_km": vendor["service_radius_km"],
            "item_count": item_count,
            "available_count": available_count,
        }
