"""Generic enterprise-integration connector contract + shared adapter helpers.

Mirrors the LLM provider abstraction in ``app.retailops.providers``: a
domain-neutral interface, an optional "real" adapter that speaks to a
configurable REST endpoint, and a deterministic mock/fake fallback used for
the credential-free pilot. No credentials are hardcoded anywhere in this
package — every secret is read from the environment at call time, and a
missing/invalid credential degrades honestly (``disabled`` / ``configured``
/ ``error``) rather than fabricating vendor data.

Every connector implements the same async contract regardless of whether it
is "mock-functional" (deterministic fictional data, safe for demos) or an
"honest stub" (no vendor adapter implemented yet for this pilot):

    connector_id / display_name / capabilities / read_only
    health() / test_connection() / pull() / normalize() / push()
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from app.core.http_errors import error_kind


class ConnectorStatus(str):
    """Closed set of connector statuses (plain str subclass constants).

    Kept as string constants (not an ``enum.Enum``) so connector code can
    return them directly as JSON-safe values without an extra ``.value``.
    """

    DISABLED = "disabled"
    MOCK = "mock"
    CONFIGURED = "configured"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    ERROR = "error"


ALL_STATUSES = frozenset(
    {
        ConnectorStatus.DISABLED,
        ConnectorStatus.MOCK,
        ConnectorStatus.CONFIGURED,
        ConnectorStatus.CONNECTED,
        ConnectorStatus.DEGRADED,
        ConnectorStatus.ERROR,
    }
)


class ConnectorError(RuntimeError):
    """Raised on connector misconfiguration or upstream failure.

    Connector failures always raise ``ConnectorError`` — they never cause a
    handler to fabricate pull/push output. Callers (the API layer) turn this
    into an honest, non-2xx-free response and an audit run record.
    """

    def __init__(self, message: str, *, error_code: str = "connector_error") -> None:
        super().__init__(message)
        self.error_code = error_code


class ConnectorBadge(BaseModel):
    """A short, honest UI badge (e.g. ``Credentials required``, ``Read-only``)."""

    label: str
    tone: str = "neutral"  # neutral | positive | warning | info


class RetailConnector:
    """Base class for every RetailOps enterprise integration connector.

    Subclasses set the class-level metadata attributes and implement the
    five async methods. ``mock_functional=True`` connectors must produce
    deterministic fictional data from :meth:`pull`/:meth:`normalize` with no
    outbound network calls when no real credentials are configured. Stub
    connectors must never fabricate vendor data — they raise
    :class:`ConnectorError` with an honest, actionable message instead.
    """

    connector_id: str = "base"
    display_name: str = "Base Connector"
    category: str = "generic"
    vendor_examples: List[str] = []
    capabilities: List[str] = []
    read_only: bool = True
    mock_functional: bool = False
    planned_capabilities: List[str] = []
    description: str = ""

    def status(self) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def badges(self) -> List[ConnectorBadge]:
        """Honest UI badges. Subclasses may override; default is status-derived."""
        status = self.status()
        badges: List[ConnectorBadge] = []
        if status == ConnectorStatus.DISABLED:
            badges.append(ConnectorBadge(label="Not connected", tone="neutral"))
            badges.append(ConnectorBadge(label="Credentials required", tone="warning"))
        elif status == ConnectorStatus.MOCK:
            badges.append(ConnectorBadge(label="Mock available", tone="info"))
        elif status == ConnectorStatus.CONFIGURED:
            badges.append(ConnectorBadge(label="Configured", tone="info"))
        elif status == ConnectorStatus.CONNECTED:
            badges.append(ConnectorBadge(label="Connected", tone="positive"))
        elif status == ConnectorStatus.DEGRADED:
            badges.append(ConnectorBadge(label="Degraded", tone="warning"))
        elif status == ConnectorStatus.ERROR:
            badges.append(ConnectorBadge(label="Error", tone="warning"))
        if self.read_only:
            badges.append(ConnectorBadge(label="Read-only", tone="neutral"))
        if self.planned_capabilities:
            badges.append(ConnectorBadge(label="Planned capability", tone="neutral"))
        return badges

    async def health(self) -> Dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError

    async def test_connection(self) -> Dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError

    async def pull(
        self, *, cursor: Optional[str] = None, since: Optional[str] = None
    ) -> Dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:  # pragma: no cover - interface
        raise NotImplementedError

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError

    def public_dict(self) -> Dict[str, Any]:
        """Deterministic, JSON-safe card summary for the ``/v1/integrations`` list."""
        return {
            "connector_id": self.connector_id,
            "display_name": self.display_name,
            "category": self.category,
            "description": self.description,
            "vendor_examples": list(self.vendor_examples),
            "capabilities": list(self.capabilities),
            "planned_capabilities": list(self.planned_capabilities),
            "read_only": self.read_only,
            "mock_functional": self.mock_functional,
            "status": self.status(),
            "badges": [b.model_dump() for b in self.badges()],
        }


# ---------------------------------------------------------------------------
# Shared helpers for building mock-functional + generic-REST connectors
# ---------------------------------------------------------------------------


def deterministic_rng(*parts: str) -> random.Random:
    """A ``random.Random`` seeded deterministically from the given parts.

    Used by mock-functional connectors so the same connector/cursor always
    produces the same fictional dataset — required by "deterministic
    fictional data" (never random-per-call, never fabricated per real facts).
    """
    seed_material = "|".join(parts).encode("utf-8")
    seed = int(hashlib.sha256(seed_material).hexdigest(), 16)
    return random.Random(seed)


class GenericRestMixin:
    """Optional real adapter: a minimal, generic authenticated REST GET/POST.

    This mirrors ``OpenAICompatibleProvider`` in ``app.retailops.providers``:
    a single generic, vendor-agnostic real HTTP path used only when a base
    URL + API key are configured via environment variables. It is never
    required — connectors fall back to their deterministic mock generator
    when it is absent or the call fails, and always raise
    :class:`ConnectorError` rather than silently returning fabricated data
    labelled as real.
    """

    base_url: str = ""
    api_key: str = ""

    def rest_available(self) -> bool:
        return bool(self.base_url and self.api_key)

    async def rest_get_json(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
        if not self.rest_available():
            raise mark_unavailable(ConnectorError("generic REST adapter is not configured", error_code="not_configured"))
        import httpx

        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    url, params=params, headers={"Authorization": f"Bearer {self.api_key}"}
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"generic REST request failed: {exc}", error_code="upstream_error") from exc

    async def rest_post_json(self, path: str, *, json_body: Optional[Dict[str, Any]] = None) -> Any:
        if not self.rest_available():
            raise mark_unavailable(ConnectorError("generic REST adapter is not configured", error_code="not_configured"))
        import httpx

        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url, json=json_body or {}, headers={"Authorization": f"Bearer {self.api_key}"}
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"generic REST request failed: {exc}", error_code="upstream_error") from exc

"""Shared deterministic fictional reference data for mock-functional connectors.

All values here are invented for the pilot (no real retailer, store, SKU or
supplier names). Every generator is a pure function of its inputs — same
connector id + cursor always yields the same records — so demos, screenshots
and tests are reproducible.
"""



# base contract symbols are defined above in this same module

STORE_IDS = [f"ST-{n:03d}" for n in (101, 102, 103, 104, 105)]
TILL_IDS = ["T1", "T2", "T3", "T4"]
WAREHOUSE_IDS = ["WH-NORTH", "WH-SOUTH", "WH-CENTRAL"]
PAYMENT_TYPES = ["card", "cash", "mobile_wallet", "gift_card"]
SKUS = [
    ("BEV-2201", "Sparkling Water 500ml"),
    ("SNK-1180", "Trail Mix 250g"),
    ("DRY-3305", "Pasta 500g"),
    ("CHL-4410", "Greek Yoghurt 4-pack"),
    ("HHC-5520", "Dish Soap 750ml"),
    ("BKY-6630", "Sourdough Loaf"),
    ("FRZ-7741", "Frozen Berries 400g"),
    ("PRO-8852", "Chicken Breast 1kg"),
]
SUPPLIER_IDS = ["SUP-ALPINE", "SUP-HARBOUR", "SUP-MERIDIAN"]


def sku_catalog() -> List[Dict[str, str]]:
    return [{"sku": sku, "description": desc} for sku, desc in SKUS]


def pos_transactions(seed_key: str, count: int = 12) -> List[Dict[str, Any]]:
    """Fictional vendor-shaped POS transaction feed (raw, pre-normalize)."""
    rng = deterministic_rng("pos", seed_key)
    records: List[Dict[str, Any]] = []
    for i in range(count):
        sku, _desc = rng.choice(SKUS)
        qty = rng.randint(1, 5)
        unit_price = round(rng.uniform(1.5, 24.0), 2)
        is_return = rng.random() < 0.08
        discount = round(unit_price * qty * rng.choice([0, 0, 0, 0.1, 0.15]), 2)
        records.append(
            {
                "txn_id": f"TXN-{seed_key[:4].upper()}-{i:05d}",
                "store_id": rng.choice(STORE_IDS),
                "till_id": rng.choice(TILL_IDS),
                "ts": f"2026-07-{(i % 28) + 1:02d}T{8 + (i % 10):02d}:{(i * 7) % 60:02d}:00Z",
                "sku": sku,
                "qty": qty,
                "unit_price": unit_price,
                "discount": discount,
                "payment_type": rng.choice(PAYMENT_TYPES),
                "type": "return" if is_return else "sale",
            }
        )
    return records


def wms_inventory_events(seed_key: str, count: int = 12) -> List[Dict[str, Any]]:
    """Fictional vendor-shaped WMS inventory snapshot + movement feed."""
    rng = deterministic_rng("wms", seed_key)
    records: List[Dict[str, Any]] = []
    for i in range(count):
        sku, _desc = rng.choice(SKUS)
        on_hand = rng.randint(0, 250)
        reserved = rng.randint(0, min(40, on_hand))
        reorder_point = rng.randint(20, 60)
        safety_stock = rng.randint(5, 20)
        event_type = rng.choice(["transfer", "receipt", "adjustment", "snapshot"])
        qty_delta = rng.choice([0, 0, rng.randint(-15, 15)])
        records.append(
            {
                "warehouse_id": rng.choice(WAREHOUSE_IDS),
                "store_id": rng.choice(STORE_IDS),
                "sku": sku,
                "on_hand": on_hand,
                "available": max(0, on_hand - reserved),
                "reserved": reserved,
                "reorder_point": reorder_point,
                "safety_stock": safety_stock,
                "average_daily_sales": round(rng.uniform(0.5, 12.0), 1),
                "event_type": event_type,
                "qty_delta": qty_delta,
                "ts": f"2026-07-{(i % 28) + 1:02d}T06:00:00Z",
            }
        )
    return records


def edi_supplier_orders(seed_key: str, count: int = 10) -> List[Dict[str, Any]]:
    """Fictional EDI 850/856/810-shaped supplier order + delivery feed."""
    rng = deterministic_rng("edi", seed_key)
    records: List[Dict[str, Any]] = []
    for i in range(count):
        sku, _desc = rng.choice(SKUS)
        qty_ordered = rng.randint(50, 400)
        shortfall = rng.choice([0, 0, 0, rng.randint(1, 20)])
        damaged = rng.choice([0, 0, 0, rng.randint(1, 8)])
        rejected = rng.choice([0, 0, rng.randint(1, 5)])
        qty_received = max(0, qty_ordered - shortfall - damaged - rejected)
        promised_day = (i % 27) + 1
        actual_day = promised_day + rng.choice([0, 0, 1, 2, -1])
        notice_type = rng.choice([None, None, "delay", "quality_hold", "substitution"])
        records.append(
            {
                "po_number": f"PO-{seed_key[:3].upper()}-{2600 + i}",
                "supplier_id": rng.choice(SUPPLIER_IDS),
                "sku": sku,
                "qty_ordered": qty_ordered,
                "promised_date": f"2026-07-{promised_day:02d}",
                "actual_date": f"2026-07-{max(1, min(28, actual_day)):02d}",
                "qty_received": qty_received,
                "qty_short": shortfall,
                "qty_damaged": damaged,
                "qty_rejected": rejected,
                "notice_type": notice_type,
                "notice_text": (
                    f"{notice_type.replace('_', ' ').title()} notice for {sku} on PO-{2600 + i}."
                    if notice_type
                    else None
                ),
            }
        )
    return records


def power_bi_kpi_rows(seed_key: str, count: int = 14) -> List[Dict[str, Any]]:
    """Fictional daily KPI rows for the Power BI export/publish stub."""
    rng = deterministic_rng("powerbi", seed_key)
    rows: List[Dict[str, Any]] = []
    for i in range(count):
        store = rng.choice(STORE_IDS)
        rows.append(
            {
                "date": f"2026-07-{(i % 28) + 1:02d}",
                "store_id": store,
                "total_sales": round(rng.uniform(4000, 22000), 2),
                "transaction_count": rng.randint(120, 900),
                "stockout_events": rng.randint(0, 6),
                "supplier_delay_events": rng.randint(0, 3),
            }
        )
    return rows

"""POS connector — NCR / Toshiba / D365 Commerce / Generic.

Mock-functional: deterministic fictional transactions, sales by SKU, returns,
discounts, store/till/timestamp/payment-type — no real vendor API calls.

If ``RETAILOPS_POS_BASE_URL`` + ``RETAILOPS_POS_API_KEY`` are configured, the
connector reports ``configured`` and *would* use the generic REST adapter for
a real pull; this pilot does not ship vendor-specific (NCR/Toshiba/D365)
client code, so real pulls still raise :class:`ConnectorError` honestly
rather than pretending to fetch live data.
"""


import os
from datetime import datetime, timezone

# base contract symbols are defined above in this same module
# mock_data symbols are defined above in this same module

VENDORS = ["ncr", "toshiba", "d365_commerce", "generic"]


class PosConnector(GenericRestMixin, RetailConnector):
    connector_id = "pos"
    display_name = "POS"
    category = "point_of_sale"
    vendor_examples = ["NCR", "Toshiba", "D365 Commerce", "Generic"]
    capabilities = [
        "transactions", "sales_by_sku", "returns", "discounts",
        "store", "till", "timestamp", "payment_type",
    ]
    read_only = True
    mock_functional = True
    description = (
        "Point-of-sale transaction feed: sales, returns and discounts by SKU, "
        "store and till, with payment type and timestamp."
    )

    def __init__(self) -> None:
        self.vendor = os.getenv("RETAILOPS_POS_VENDOR", "generic").lower()
        self.base_url = os.getenv("RETAILOPS_POS_BASE_URL", "")
        self.api_key = os.getenv("RETAILOPS_POS_API_KEY", "")

    def status(self) -> str:
        if self.rest_available():
            return ConnectorStatus.CONFIGURED
        return ConnectorStatus.MOCK

    def badges(self) -> List[ConnectorBadge]:
        badges = super().badges()
        badges.append(ConnectorBadge(label=f"vendor: {self.vendor}", tone="neutral"))
        return badges

    async def health(self) -> Dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "status": self.status(),
            "vendor": self.vendor,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    async def test_connection(self) -> Dict[str, Any]:
        if self.rest_available():
            try:
                await self.rest_get_json("health")
                return {"ok": True, "status": ConnectorStatus.CONNECTED, "message": "Generic REST POS endpoint reachable."}
            except ConnectorError as exc:
                return {"ok": False, "status": ConnectorStatus.ERROR, "message": str(exc)}
        return {
            "ok": True,
            "status": ConnectorStatus.MOCK,
            "message": (
                "No POS endpoint configured — running in deterministic mock mode. "
                "Set RETAILOPS_POS_BASE_URL and RETAILOPS_POS_API_KEY to test a real "
                "generic REST endpoint."
            ),
        }

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        if self.rest_available():
            try:
                data = await self.rest_get_json("transactions", params={"cursor": cursor, "since": since})
                return {"records": data.get("records", []), "next_cursor": data.get("next_cursor"), "source": "rest"}
            except ConnectorError:
                raise
        seed_key = cursor or since or "default"
        records = pos_transactions(seed_key)
        return {"records": records, "next_cursor": f"pos-{seed_key}-next", "source": "mock"}

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for rec in records:
            qty = rec.get("qty", 0)
            unit_price = rec.get("unit_price", 0.0)
            discount = rec.get("discount", 0.0)
            amount = round(qty * unit_price - discount, 2)
            normalized.append(
                {
                    "transaction_id": rec.get("txn_id"),
                    "store": rec.get("store_id"),
                    "till": rec.get("till_id"),
                    "timestamp": rec.get("ts"),
                    "sku": rec.get("sku"),
                    "quantity": qty,
                    "unit_price": unit_price,
                    "discount": discount,
                    "amount": amount,
                    "payment_type": rec.get("payment_type"),
                    "record_type": rec.get("type", "sale"),
                }
            )
        return normalized

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectorError(
            "POS connector is read-only in this pilot; push is not supported.",
            error_code="read_only",
        )



"""Inventory & WMS connector — Manhattan / Blue Yonder / RELEX / Generic.

Mock-functional: deterministic fictional on-hand/available/reserved by
warehouse, reorder/safety thresholds, transfers, receipts and adjustments.

Soft-wired to the existing ``retail.analyse_inventory_risk`` action: the
canonical field names produced by :meth:`normalize` (``sku``, ``on_hand``,
``reorder_point``, ``safety_stock``, ``average_daily_sales``, ``store``) match
``app.retailops.kit.domains.retail.schemas.INVENTORY_ALIASES`` exactly, so a
caller can feed ``to_inventory_risk_rows(normalized)`` straight into that
action's ``rows`` input without any extra mapping.
"""



# base contract symbols are defined above in this same module
# mock_data symbols are defined above in this same module

VENDORS = ["manhattan", "blue_yonder", "relex", "generic"]


class InventoryWmsConnector(GenericRestMixin, RetailConnector):
    connector_id = "inventory_wms"
    display_name = "Inventory & WMS"
    category = "inventory"
    vendor_examples = ["Manhattan", "Blue Yonder", "RELEX", "Generic"]
    capabilities = [
        "on_hand", "available", "reserved", "warehouse",
        "reorder_point", "safety_stock", "transfers", "receipts", "adjustments",
    ]
    read_only = True
    mock_functional = True
    description = (
        "Warehouse/inventory feed: on-hand, available and reserved stock by "
        "warehouse and SKU, with reorder/safety thresholds and movement events."
    )

    def __init__(self) -> None:
        self.vendor = os.getenv("RETAILOPS_WMS_VENDOR", "generic").lower()
        self.base_url = os.getenv("RETAILOPS_WMS_BASE_URL", "")
        self.api_key = os.getenv("RETAILOPS_WMS_API_KEY", "")

    def status(self) -> str:
        if self.rest_available():
            return ConnectorStatus.CONFIGURED
        return ConnectorStatus.MOCK

    def badges(self) -> List[ConnectorBadge]:
        badges = super().badges()
        badges.append(ConnectorBadge(label=f"vendor: {self.vendor}", tone="neutral"))
        return badges

    async def health(self) -> Dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "status": self.status(),
            "vendor": self.vendor,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    async def test_connection(self) -> Dict[str, Any]:
        if self.rest_available():
            try:
                await self.rest_get_json("health")
                return {"ok": True, "status": ConnectorStatus.CONNECTED, "message": "Generic REST WMS endpoint reachable."}
            except ConnectorError as exc:
                return {"ok": False, "status": ConnectorStatus.ERROR, "message": str(exc)}
        return {
            "ok": True,
            "status": ConnectorStatus.MOCK,
            "message": (
                "No WMS endpoint configured — running in deterministic mock mode. "
                "Set RETAILOPS_WMS_BASE_URL and RETAILOPS_WMS_API_KEY to test a real "
                "generic REST endpoint."
            ),
        }

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        if self.rest_available():
            try:
                data = await self.rest_get_json("inventory", params={"cursor": cursor, "since": since})
                return {"records": data.get("records", []), "next_cursor": data.get("next_cursor"), "source": "rest"}
            except ConnectorError:
                raise
        seed_key = cursor or since or "default"
        records = wms_inventory_events(seed_key)
        return {"records": records, "next_cursor": f"wms-{seed_key}-next", "source": "mock"}

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for rec in records:
            normalized.append(
                {
                    "warehouse": rec.get("warehouse_id"),
                    "store": rec.get("store_id"),
                    "sku": rec.get("sku"),
                    "on_hand": rec.get("on_hand"),
                    "available": rec.get("available"),
                    "reserved": rec.get("reserved"),
                    "reorder_point": rec.get("reorder_point"),
                    "safety_stock": rec.get("safety_stock"),
                    "average_daily_sales": rec.get("average_daily_sales"),
                    "event_type": rec.get("event_type"),
                    "quantity_delta": rec.get("qty_delta", 0),
                    "timestamp": rec.get("ts"),
                }
            )
        return normalized

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectorError(
            "Inventory & WMS connector is read-only in this pilot; push is not supported.",
            error_code="read_only",
        )


def to_inventory_risk_rows(normalized_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map normalized WMS records to ``retail.analyse_inventory_risk`` rows.

    Field names already match ``INVENTORY_ALIASES`` canonical keys, so this is
    a pass-through projection — documented here so the mapping is explicit and
    doesn't silently drift if either schema changes.
    """
    rows: List[Dict[str, Any]] = []
    for rec in normalized_records:
        rows.append(
            {
                "sku": rec.get("sku"),
                "on_hand": rec.get("on_hand"),
                "reorder_point": rec.get("reorder_point"),
                "safety_stock": rec.get("safety_stock"),
                "average_daily_sales": rec.get("average_daily_sales"),
                "store": rec.get("store"),
            }
        )
    return rows



"""CRM & Loyalty connector — honest stub with a small illustrative sample.

No CRM/loyalty vendor adapter is implemented in this pilot. Unlike the other
three stubs, ``pull()`` does not hard-error: it returns a small, clearly
labelled *illustrative* fictional read-only sample (a handful of loyalty
records) rather than nothing, so the card is not entirely inert when a user
presses "Sync" — but this remains a stub, not a mock-functional connector:
there is no real vendor adapter, no pagination/cursor semantics, and the
sample is intentionally tiny and documented as illustrative only.
"""



# base contract symbols are defined above in this same module

VENDORS = ["salesforce_loyalty", "generic_crm"]

_TIERS = ["bronze", "silver", "gold", "platinum"]


class CrmLoyaltyConnector(RetailConnector):
    connector_id = "crm_loyalty"
    display_name = "CRM & Loyalty"
    category = "crm"
    vendor_examples = ["Salesforce Loyalty", "Generic CRM"]
    capabilities = ["loyalty_profile_sample"]
    planned_capabilities = ["customer_360", "campaign_membership", "loyalty_ledger"]
    read_only = True
    mock_functional = False
    description = (
        "Customer relationship + loyalty program integration. Not connected "
        "in this pilot; a tiny illustrative read-only sample is available on "
        "sync, but there is no live vendor adapter."
    )

    def __init__(self) -> None:
        self.base_url = os.getenv("RETAILOPS_CRM_BASE_URL", "")
        self.api_key = os.getenv("RETAILOPS_CRM_API_KEY", "")

    def available(self) -> bool:
        return bool(self.base_url and self.api_key)

    def status(self) -> str:
        return ConnectorStatus.CONFIGURED if self.available() else ConnectorStatus.DISABLED

    def badges(self) -> List[ConnectorBadge]:
        badges = super().badges()
        badges.append(ConnectorBadge(label="Illustrative sample only", tone="info"))
        return badges

    async def health(self) -> Dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "status": self.status(),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    async def test_connection(self) -> Dict[str, Any]:
        if not self.available():
            return {
                "ok": False,
                "status": ConnectorStatus.DISABLED,
                "message": (
                    "CRM & Loyalty credentials are not configured. This connector "
                    "is a stub — sync returns a tiny illustrative read-only sample, "
                    "not a live feed."
                ),
            }
        return {
            "ok": False,
            "status": ConnectorStatus.CONFIGURED,
            "message": (
                "Credentials detected, but a real CRM/loyalty adapter is not "
                "implemented in this pilot. No connection was attempted."
            ),
        }

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        rng = deterministic_rng("crm_loyalty", cursor or since or "sample")
        records = [
            {
                "customer_id": f"CUST-{4000 + i}",
                "loyalty_tier": rng.choice(_TIERS),
                "points_balance": rng.randint(0, 5000),
                "email_opt_in": rng.random() < 0.7,
                "last_purchase_date": f"2026-06-{(i % 28) + 1:02d}",
            }
            for i in range(5)
        ]
        return {
            "records": records,
            "next_cursor": None,
            "source": "illustrative_sample",
            "note": "Tiny fictional sample for UI demonstration only — not a live CRM feed.",
        }

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "customer_id": rec.get("customer_id"),
                "loyalty_tier": rec.get("loyalty_tier"),
                "points_balance": rec.get("points_balance"),
                "email_opt_in": rec.get("email_opt_in"),
                "last_purchase_date": rec.get("last_purchase_date"),
            }
            for rec in records
        ]

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectorError(
            "CRM & Loyalty connector is read-only in this pilot; push is not supported.",
            error_code="read_only",
        )



"""Supplier / EDI connector — Ariba / EDI 850/856/810 / Portal.

Mock-functional: deterministic fictional purchase orders with promised vs.
actual delivery, quantities, short/damaged/rejected counts, and notices.
"""



# base contract symbols are defined above in this same module
# mock_data symbols are defined above in this same module

VENDORS = ["ariba", "edi_850", "edi_856", "edi_810", "portal", "generic"]


class SupplierEdiConnector(GenericRestMixin, RetailConnector):
    connector_id = "supplier_edi"
    display_name = "Supplier / EDI"
    category = "supply_chain"
    vendor_examples = ["Ariba", "EDI 850", "EDI 856", "EDI 810", "Portal"]
    capabilities = [
        "orders", "promised_delivery", "actual_delivery", "quantities",
        "short", "damaged", "rejected", "notices",
    ]
    read_only = True
    mock_functional = True
    description = (
        "Supplier order and delivery feed: purchase orders, promised vs. "
        "actual delivery dates, quantities and short/damaged/rejected notices."
    )

    def __init__(self) -> None:
        self.vendor = os.getenv("RETAILOPS_EDI_VENDOR", "generic").lower()
        self.base_url = os.getenv("RETAILOPS_EDI_BASE_URL", "")
        self.api_key = os.getenv("RETAILOPS_EDI_API_KEY", "")

    def status(self) -> str:
        if self.rest_available():
            return ConnectorStatus.CONFIGURED
        return ConnectorStatus.MOCK

    def badges(self) -> List[ConnectorBadge]:
        badges = super().badges()
        badges.append(ConnectorBadge(label=f"vendor: {self.vendor}", tone="neutral"))
        return badges

    async def health(self) -> Dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "status": self.status(),
            "vendor": self.vendor,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    async def test_connection(self) -> Dict[str, Any]:
        if self.rest_available():
            try:
                await self.rest_get_json("health")
                return {"ok": True, "status": ConnectorStatus.CONNECTED, "message": "Generic REST EDI endpoint reachable."}
            except ConnectorError as exc:
                return {"ok": False, "status": ConnectorStatus.ERROR, "message": str(exc)}
        return {
            "ok": True,
            "status": ConnectorStatus.MOCK,
            "message": (
                "No supplier/EDI endpoint configured — running in deterministic "
                "mock mode. Set RETAILOPS_EDI_BASE_URL and RETAILOPS_EDI_API_KEY to "
                "test a real generic REST endpoint."
            ),
        }

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        if self.rest_available():
            try:
                data = await self.rest_get_json("orders", params={"cursor": cursor, "since": since})
                return {"records": data.get("records", []), "next_cursor": data.get("next_cursor"), "source": "rest"}
            except ConnectorError:
                raise
        seed_key = cursor or since or "default"
        records = edi_supplier_orders(seed_key)
        return {"records": records, "next_cursor": f"edi-{seed_key}-next", "source": "mock"}

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for rec in records:
            normalized.append(
                {
                    "order_id": rec.get("po_number"),
                    "supplier_id": rec.get("supplier_id"),
                    "sku": rec.get("sku"),
                    "quantity_ordered": rec.get("qty_ordered"),
                    "promised_delivery": rec.get("promised_date"),
                    "actual_delivery": rec.get("actual_date"),
                    "quantity_received": rec.get("qty_received"),
                    "quantity_short": rec.get("qty_short", 0),
                    "quantity_damaged": rec.get("qty_damaged", 0),
                    "quantity_rejected": rec.get("qty_rejected", 0),
                    "notice_type": rec.get("notice_type"),
                    "notice_text": rec.get("notice_text"),
                }
            )
        return normalized

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectorError(
            "Supplier / EDI connector is read-only in this pilot; push is not supported.",
            error_code="read_only",
        )



"""Microsoft Entra ID connector — honest stub for SSO / roles / group mapping.

No SSO federation, role or group-mapping sync is implemented in this pilot.
RetailOps itself is not registered as an Entra ID application. If tenant /
client credentials are set, the connector reports ``configured`` (detected,
not attempted) — it never calls Microsoft Graph or performs a token exchange
in this pilot, and never fabricates roles/groups/users.
"""



# base contract symbols are defined above in this same module


class EntraIdConnector(RetailConnector):
    connector_id = "entra_id"
    display_name = "Microsoft Entra ID"
    category = "identity"
    vendor_examples = ["Microsoft Entra ID"]
    capabilities = []
    planned_capabilities = ["sso", "role_mapping", "group_mapping"]
    read_only = True
    mock_functional = False
    description = (
        "SSO, role and group-mapping integration with Microsoft Entra ID. "
        "Not connected in this pilot — planned capability for a future "
        "release; RetailOps uses server-resolved X-User-Id/X-Tenant-Id/"
        "X-Project-Id headers today."
    )

    def __init__(self) -> None:
        self.tenant_id = os.getenv("RETAILOPS_ENTRA_TENANT_ID", "")
        self.client_id = os.getenv("RETAILOPS_ENTRA_CLIENT_ID", "")
        self.client_secret = os.getenv("RETAILOPS_ENTRA_CLIENT_SECRET", "")

    def available(self) -> bool:
        return bool(self.tenant_id and self.client_id and self.client_secret)

    def status(self) -> str:
        return ConnectorStatus.CONFIGURED if self.available() else ConnectorStatus.DISABLED

    def badges(self) -> List[ConnectorBadge]:
        badges = super().badges()
        badges.append(ConnectorBadge(label="SSO / roles / groups: planned", tone="neutral"))
        return badges

    async def health(self) -> Dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "status": self.status(),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    async def test_connection(self) -> Dict[str, Any]:
        if not self.available():
            return {
                "ok": False,
                "status": ConnectorStatus.DISABLED,
                "message": (
                    "Microsoft Entra ID credentials are not configured. SSO, role "
                    "and group mapping are planned capabilities in this pilot."
                ),
            }
        return {
            "ok": False,
            "status": ConnectorStatus.CONFIGURED,
            "message": (
                "Credentials detected, but SSO/role/group-mapping sync is not "
                "implemented in this pilot. No connection was attempted."
            ),
        }

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        raise ConnectorError(
            "Microsoft Entra ID pull (roles/groups) is not implemented in this pilot (planned capability).",
            error_code="not_implemented",
        )

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        raise ConnectorError(
            "Microsoft Entra ID normalize is not implemented in this pilot (planned capability).",
            error_code="not_implemented",
        )

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectorError(
            "Microsoft Entra ID push is not implemented in this pilot (planned capability).",
            error_code="not_implemented",
        )



"""Power BI connector — export, publish/refresh stubs, embed placeholder.

Mock-functional (per the pilot scope): the KPI dataset pull and CSV/XLSX
export are real, working code paths — no fabricated files, just genuinely
generated CSV/XLSX bytes from deterministic fictional KPI rows (or caller
-supplied rows). "Publish dataset" and "refresh semantic model" stay honest
stubs (Power BI dataset/refresh APIs are not implemented in this pilot); the
embed dashboard URL is an explicit placeholder, never a fabricated real link.

If ``RETAILOPS_POWERBI_TENANT_ID`` / ``_CLIENT_ID`` / ``_CLIENT_SECRET`` /
``_WORKSPACE_ID`` are all configured, :meth:`test_connection` performs a real
Azure AD client-credentials token request + a real Power BI REST call to
verify workspace access. No credentials are hardcoded; nothing is attempted
without them.
"""


import base64
import csv
import io

# base contract symbols are defined above in this same module
# mock_data symbols are defined above in this same module

_AAD_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_POWERBI_API = "https://api.powerbi.com/v1.0/myorg"
_POWERBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"


class PowerBiConnector(RetailConnector):
    connector_id = "power_bi"
    display_name = "Power BI"
    category = "analytics_export"
    vendor_examples = ["Microsoft Power BI"]
    capabilities = [
        "export_csv", "export_xlsx", "kpi_dataset_pull",
    ]
    planned_capabilities = ["publish_dataset", "refresh_semantic_model", "embed_dashboard"]
    read_only = False
    mock_functional = True
    description = (
        "KPI export to Power BI: deterministic KPI dataset, real CSV/XLSX "
        "download. Dataset publish, semantic-model refresh and dashboard "
        "embed are documented stubs — not implemented against a live "
        "workspace in this pilot."
    )

    def __init__(self) -> None:
        self.tenant_id = os.getenv("RETAILOPS_POWERBI_TENANT_ID", "")
        self.client_id = os.getenv("RETAILOPS_POWERBI_CLIENT_ID", "")
        self.client_secret = os.getenv("RETAILOPS_POWERBI_CLIENT_SECRET", "")
        self.workspace_id = os.getenv("RETAILOPS_POWERBI_WORKSPACE_ID", "")

    def available(self) -> bool:
        return bool(self.tenant_id and self.client_id and self.client_secret and self.workspace_id)

    def status(self) -> str:
        if self.available():
            return ConnectorStatus.CONFIGURED
        return ConnectorStatus.MOCK

    def badges(self) -> List[ConnectorBadge]:
        badges = super().badges()
        badges.append(ConnectorBadge(label="Publish/refresh: stub", tone="neutral"))
        badges.append(ConnectorBadge(label="Embed URL: placeholder", tone="neutral"))
        return badges

    async def health(self) -> Dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "status": self.status(),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _acquire_token(self) -> str:
        import httpx

        url = _AAD_TOKEN_URL.format(tenant=self.tenant_id)
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": _POWERBI_SCOPE,
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, data=data)
                resp.raise_for_status()
                token = resp.json().get("access_token")
                if not token:
                    raise ConnectorError("Azure AD token response missing access_token")
                return token
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"Azure AD token request failed: {exc}", error_code="auth_failed") from exc

    async def test_connection(self) -> Dict[str, Any]:
        if not self.available():
            return {
                "ok": True,
                "status": ConnectorStatus.MOCK,
                "message": (
                    "No Power BI workspace configured — CSV/XLSX export works in "
                    "mock mode. Set RETAILOPS_POWERBI_TENANT_ID/_CLIENT_ID/"
                    "_CLIENT_SECRET/_WORKSPACE_ID for a real connectivity test."
                ),
            }
        import httpx

        try:
            token = await self._acquire_token()
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{_POWERBI_API}/groups/{self.workspace_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
            return {"ok": True, "status": ConnectorStatus.CONNECTED, "message": "Power BI workspace reachable."}
        except ConnectorError as exc:
            return {"ok": False, "status": ConnectorStatus.ERROR, "message": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": ConnectorStatus.ERROR, "message": f"Power BI request failed: {exc}"}

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        seed_key = cursor or since or "default"
        rows = power_bi_kpi_rows(seed_key)
        return {"records": rows, "next_cursor": f"powerbi-{seed_key}-next", "source": "mock"}

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "date": rec.get("date"),
                "store": rec.get("store_id"),
                "total_sales": rec.get("total_sales"),
                "transaction_count": rec.get("transaction_count"),
                "stockout_events": rec.get("stockout_events"),
                "supplier_delay_events": rec.get("supplier_delay_events"),
            }
            for rec in records
        ]

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if operation == "export_csv":
            return self._export_csv(payload)
        if operation == "export_xlsx":
            return self._export_xlsx(payload)
        if operation == "publish_dataset":
            return {
                "ok": False,
                "status": "not_implemented",
                "message": (
                    "Publishing a KPI dataset to a live Power BI workspace is not "
                    "implemented in this pilot. This is an honest stub."
                ),
            }
        if operation == "refresh_semantic_model":
            return {
                "ok": False,
                "status": "not_implemented",
                "message": (
                    "Triggering a semantic model refresh is not implemented in "
                    "this pilot. This is an honest stub."
                ),
            }
        if operation == "get_embed_url":
            return {
                "ok": True,
                "status": "placeholder",
                "embed_url": "https://app.powerbi.com/reportEmbed?reportId=PLACEHOLDER",
                "message": "Placeholder embed URL — no live dashboard is provisioned in this pilot.",
            }
        raise ConnectorError(f"unsupported Power BI operation: {operation}", error_code="unsupported_operation")

    def _rows_for_export(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = payload.get("rows")
        if isinstance(rows, list) and rows:
            return rows
        return power_bi_kpi_rows(payload.get("cursor") or "export")

    def _export_csv(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        rows = self._rows_for_export(payload)
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return {
            "ok": True,
            "status": "exported",
            "filename": "retailops-kpi-export.csv",
            "content_type": "text/csv",
            "content_base64": base64.b64encode(buf.getvalue().encode("utf-8")).decode("ascii"),
            "row_count": len(rows),
        }

    def _export_xlsx(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        rows = self._rows_for_export(payload)
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "RetailOps KPI"
        if rows:
            headers = list(rows[0].keys())
            ws.append(headers)
            for row in rows:
                ws.append([row.get(h) for h in headers])
        buf = io.BytesIO()
        wb.save(buf)
        return {
            "ok": True,
            "status": "exported",
            "filename": "retailops-kpi-export.xlsx",
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "content_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "row_count": len(rows),
        }



"""SAP / ERP connector — honest stub.

No SAP/ERP vendor adapter is implemented in this pilot. The connector never
fabricates financial, order or master-data records: without real credentials
it reports ``disabled``; with credentials present it reports ``configured``
but still declines to pull/push, since no vendor client exists yet.
"""



# base contract symbols are defined above in this same module

VENDORS = ["sap_s4hana", "sap_ecc", "generic_erp"]


class SapErpConnector(RetailConnector):
    connector_id = "sap_erp"
    display_name = "SAP / ERP"
    category = "erp"
    vendor_examples = ["SAP S/4HANA", "SAP ECC", "Generic ERP"]
    capabilities = ["general_ledger", "purchase_orders", "vendor_master", "cost_centers"]
    planned_capabilities = ["general_ledger", "purchase_orders", "vendor_master", "cost_centers"]
    read_only = True
    mock_functional = False
    description = (
        "Enterprise resource planning integration (financials, purchasing, "
        "vendor master data). Not connected in this pilot — planned capability."
    )

    def __init__(self) -> None:
        self.base_url = os.getenv("RETAILOPS_SAP_BASE_URL", "")
        self.client_id = os.getenv("RETAILOPS_SAP_CLIENT_ID", "")
        self.api_key = os.getenv("RETAILOPS_SAP_API_KEY", "")

    def available(self) -> bool:
        return bool(self.base_url and self.client_id and self.api_key)

    def status(self) -> str:
        return ConnectorStatus.CONFIGURED if self.available() else ConnectorStatus.DISABLED

    def badges(self) -> List[ConnectorBadge]:
        badges = super().badges()
        badges.append(ConnectorBadge(label="Planned: general ledger, purchase orders", tone="neutral"))
        return badges

    async def health(self) -> Dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "status": self.status(),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    async def test_connection(self) -> Dict[str, Any]:
        if not self.available():
            return {
                "ok": False,
                "status": ConnectorStatus.DISABLED,
                "message": (
                    "SAP / ERP credentials are not configured. This connector is a "
                    "planned-capability stub for the pilot — no vendor adapter is "
                    "implemented yet."
                ),
            }
        return {
            "ok": False,
            "status": ConnectorStatus.CONFIGURED,
            "message": (
                "Credentials detected, but a real SAP/ERP adapter is not "
                "implemented in this pilot. No connection was attempted."
            ),
        }

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        raise ConnectorError(
            "SAP / ERP pull is not implemented in this pilot (planned capability).",
            error_code="not_implemented",
        )

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        raise ConnectorError(
            "SAP / ERP normalize is not implemented in this pilot (planned capability).",
            error_code="not_implemented",
        )

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectorError(
            "SAP / ERP push is not implemented in this pilot (planned capability).",
            error_code="not_implemented",
        )



"""Store Digital Twin connector — honest stub with a documented data shape.

UI label is deliberately "Store Digital Twin" (not "retail BIM"). No live
digital-twin/planogram service is integrated in this pilot. The planogram
record *shape* is documented below (``PLANOGRAM_RECORD_SHAPE``) so a future
real adapter has a stable contract to target, but ``pull()``/``push()`` never
fabricate planogram or fixture data — they raise :class:`ConnectorError`.
"""



# base contract symbols are defined above in this same module

VENDORS = ["generic_digital_twin"]

# Documented target shape for a future real adapter — not populated with data.
PLANOGRAM_RECORD_SHAPE: Dict[str, str] = {
    "store_id": "string",
    "planogram_id": "string",
    "fixture": "string",
    "zone": "string",
    "sku": "string",
    "facings": "integer",
    "position": "string",
    "effective_date": "date",
}


class StoreDigitalTwinConnector(RetailConnector):
    connector_id = "store_digital_twin"
    display_name = "Store Digital Twin"
    category = "digital_twin"
    vendor_examples = ["Generic Digital Twin"]
    capabilities = []
    planned_capabilities = ["planogram_sync", "fixture_layout", "zone_mapping"]
    read_only = True
    mock_functional = False
    description = (
        "Store digital twin / planogram integration. Not connected in this "
        "pilot — the planogram data shape is documented and ready, but no "
        "live adapter is implemented."
    )

    def __init__(self) -> None:
        self.base_url = os.getenv("RETAILOPS_DIGITAL_TWIN_BASE_URL", "")
        self.api_key = os.getenv("RETAILOPS_DIGITAL_TWIN_API_KEY", "")

    def available(self) -> bool:
        return bool(self.base_url and self.api_key)

    def status(self) -> str:
        return ConnectorStatus.CONFIGURED if self.available() else ConnectorStatus.DISABLED

    def badges(self) -> List[ConnectorBadge]:
        badges = super().badges()
        badges.append(ConnectorBadge(label="Planogram shape documented", tone="neutral"))
        return badges

    async def health(self) -> Dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "status": self.status(),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "planogram_record_shape": PLANOGRAM_RECORD_SHAPE,
        }

    async def test_connection(self) -> Dict[str, Any]:
        if not self.available():
            return {
                "ok": False,
                "status": ConnectorStatus.DISABLED,
                "message": (
                    "Store Digital Twin credentials are not configured. This "
                    "connector is a planned-capability stub — the planogram data "
                    "shape is documented but no live adapter exists yet."
                ),
            }
        return {
            "ok": False,
            "status": ConnectorStatus.CONFIGURED,
            "message": (
                "Credentials detected, but a real digital-twin adapter is not "
                "implemented in this pilot. No connection was attempted."
            ),
        }

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        raise ConnectorError(
            "Store Digital Twin pull is not implemented in this pilot (planned capability).",
            error_code="not_implemented",
        )

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        raise ConnectorError(
            "Store Digital Twin normalize is not implemented in this pilot (planned capability).",
            error_code="not_implemented",
        )

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectorError(
            "Store Digital Twin push is not implemented in this pilot (planned capability).",
            error_code="not_implemented",
        )



"""Facade for the ported <client> RetailOps connector contract.

Provenance: honest-stub — ported from <private-product>
backend/app/retailops/integrations/base.py (connector contract:
ConnectorStatus / ConnectorError / RetailConnector / GenericRestMixin),
mock_data.py (deterministic fictional reference data), and
connectors/{pos,inventory_wms,crm_loyalty,supplier_edi,entra_id,power_bi,
sap_erp,store_digital_twin}.py. pos/inventory_wms/crm_loyalty/supplier_edi
are mock-functional (deterministic fictional data, generic REST when
configured); sap_erp/entra_id/store_digital_twin/power_bi are honest
stubs that never fabricate vendor data and raise ConnectorError instead.
No credentials are hardcoded; secrets are read from the environment at
call time and a missing credential degrades honestly (disabled / mock /
configured / error) rather than fabricating vendor data.

The block surface dispatches to the eight ported connectors by
connector_id: list / status / health / test_connection / pull /
normalize / push. A ConnectorError raised by a connector is surfaced as
a structured refusal envelope — never as fabricated output.
"""


from app.core.universal_base import UniversalBlock
from app.core.http_errors import mark_unavailable

_CONNECTORS: Dict[str, Any] = {}


def _connector_classes():
    global _CONNECTORS
    if _CONNECTORS:
        return _CONNECTORS
    for cls in (
        PosConnector,
        InventoryWmsConnector,
        CrmLoyaltyConnector,
        SupplierEdiConnector,
        EntraIdConnector,
        PowerBiConnector,
        SapErpConnector,
        StoreDigitalTwinConnector,
    ):
        _CONNECTORS[cls.connector_id] = cls
    return _CONNECTORS


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "retail_connectors", "status": status, "result": result, "error": error, "detail": detail}


class RetailConnectorsBlock(UniversalBlock):
    """Enterprise retail integration contract ported from <client>."""

    name = "retail_connectors"
    version = "1.0.0"
    description = (
        "honest-stub: enterprise retail connector contract ported from "
        "<private-product> backend/app/retailops/integrations/base.py "
        "+ connectors/*.py (pos, inventory_wms, sap_erp, crm_loyalty, "
        "supplier_edi, entra_id, power_bi, store_digital_twin). Four connectors "
        "are mock-functional (deterministic fictional data; generic REST when "
        "RETAILOPS_*_BASE_URL/API_KEY configured); the rest are honest stubs "
        "that raise ConnectorError instead of fabricating vendor data. "
        "Unconfigured connectors report disabled/mock and never fake a pull."
    )
    layer = 3
    tags = ["retail", "connector", "integration", "pos", "wms", "erp", "edi", "honest-stub", "<client>"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "list"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "list")).lower()
        connector_id = str(payload.get("connector_id", ""))
        try:
            if action == "list":
                return self._list(payload)
            cls = self._resolve(connector_id)
            if cls is None:
                return _envelope("error", error=f"unknown connector_id: {connector_id}", detail={"known": sorted(_connector_classes())})
            conn = cls()
            if action == "status":
                return _envelope("ok", {"connector_id": conn.connector_id, "status": conn.status(), "badges": [b.model_dump() for b in conn.badges()]})
            if action == "public_dict":
                return _envelope("ok", {"connector": conn.public_dict()})
            if action == "health":
                return _envelope("ok", {"health": await conn.health()})
            if action == "test_connection":
                return _envelope("ok", {"connection": await conn.test_connection()})
            if action == "pull":
                result = await conn.pull(cursor=payload.get("cursor"), since=payload.get("since"))
                return _envelope("ok", {"pull": result})
            if action == "normalize":
                records = payload.get("records")
                if not isinstance(records, list):
                    return _envelope("error", error="normalize requires a 'records' list")
                return _envelope("ok", {"normalized": await conn.normalize(records)})
            if action == "push":
                return await self._push(conn, payload)
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["list", "status", "public_dict", "health", "test_connection", "pull", "normalize", "push"]})
        except ConnectorError as exc:
            return _envelope("refused", error=str(exc), detail={"connector_id": connector_id, "error_code": exc.error_code, "action": action})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    def _resolve(self, connector_id: str):
        return _connector_classes().get(connector_id)

    def _list(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        cards = []
        for cls in _connector_classes().values():
            try:
                cards.append(cls().public_dict())
            except Exception as exc:  # noqa: BLE001 - one broken connector must not hide the rest
                cards.append({"connector_id": cls.connector_id, "error": str(exc), "error_kind": error_kind(exc)})
        return _envelope("ok", {"connectors": cards, "count": len(cards)})

    async def _push(self, conn, payload: Dict[str, Any]) -> Dict[str, Any]:
        operation = str(payload.get("operation", ""))
        body = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        if not operation:
            return _envelope("error", error="push requires an 'operation'")
        result = await conn.push(operation, body)
        return _envelope("ok", {"push": result})
