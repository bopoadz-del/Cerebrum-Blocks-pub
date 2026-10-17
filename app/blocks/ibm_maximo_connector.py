"""IBM Maximo CMMS connector — structured asset ingest only (no Aconex/Procore/BIM).

Ported from C:\\Users\\<owner>\\<private-repo>\\connectors\\maximo.py:
- MaximoConnector.normalise (assets + workorders event mapping),
- the out-of-scope source guard (assets from aconex/procore/bim/bim_ifc
  are refused with the donor's "is out of scope" message),
- live_env_keys ("maximo_base_url", "maximo_api_key"), live_url
  (/os/<resource>) and live_headers (apikey header).

And from C:\\Users\\<owner>\\<private-repo>\\connectors\\base.py:
- connect()/fetch_live() gating: live fetch only when the live env is set;
  otherwise the donor raises ConnectorError("No fixture pack for maximo at
  ..."). This store ships no hotelops fixture pack, so unconfigured fetch
  and ingest fail closed with a structured refusal.

The hotelops event bus is not present in this store: emitted events are
returned as plain dicts with the donor's topic/surface/source/payload shape.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "ibm_maximo_connector",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


# Ported from hotelops reasoning/guard.py FORBIDDEN_SOURCES (subset the
# maximo.py normalise checks): Aconex/Procore/BIM parse is out of scope.
FORBIDDEN_SOURCES = {"aconex", "procore", "bim", "bim_ifc"}

LIVE_ENV_KEYS = ("maximo_base_url", "maximo_api_key")

KNOWN_RESOURCES = ("assets", "workorders")


class IbmMaximoConnectorBlock(UniversalBlock):
    """IBM Maximo CMMS ingest connector — real port, fail-closed without live env."""

    name = "ibm_maximo_connector"
    version = "1.0.0"
    description = (
        "real — IBM Maximo CMMS connector ported from "
        "C:\\Users\\<owner>\\<private-repo>\\connectors\\maximo.py (normalise, "
        "out-of-scope source guard, /os/<resource> live URL, apikey header) and "
        "connectors/base.py (live-env gating + fetch_live). Unconfigured fetch "
        "and ingest fail closed with a structured refusal — this store ships no "
        "hotelops fixture pack. Assets from Aconex/Procore/BIM are refused."
    )
    layer = 2
    tags = ["connector", "maximo", "cmms", "asset-management", "hotelops"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"action": "ingest", "resource": "assets", "raw": {"records": [{"asset_id": "A1"}]}}',
            "multiline": True,
        },
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}]},
    }

    def _live_configured(self) -> bool:
        return all(str(self.config.get(k, "")).strip() for k in LIVE_ENV_KEYS)

    def live_url(self, resource: str) -> str:
        # Ported from maximo.py MaximoConnector.live_url.
        return f"{str(self.config.get('maximo_base_url', '')).rstrip('/')}/os/{resource}"

    def live_headers(self) -> Dict[str, str]:
        # Ported from maximo.py MaximoConnector.live_headers.
        return {"apikey": str(self.config.get("maximo_api_key", ""))}

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "status")).lower()
        try:
            if action == "status":
                return _envelope("ok", {
                    "connector": "maximo",
                    "source": "maximo_cmms",
                    "live_configured": self._live_configured(),
                    "resources": list(KNOWN_RESOURCES),
                })
            if action == "capabilities":
                return _envelope("ok", {
                    "supported_actions": ["status", "capabilities", "fetch", "normalise", "ingest"],
                    "resources": list(KNOWN_RESOURCES),
                    "note": "structured asset/workorder ingest only — Aconex/Procore/BIM refused",
                })
            if action == "fetch":
                return self._fetch(payload)
            if action == "normalise":
                return self._normalise(payload)
            if action == "ingest":
                return self._ingest(payload)
            return _envelope(
                "error",
                error=f"unknown action: {action}",
                detail={"known": ["status", "capabilities", "fetch", "normalise", "ingest"]},
            )
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    def _require_resource(self, resource: str) -> Dict[str, Any]:
        if resource not in KNOWN_RESOURCES:
            return _envelope(
                "refused",
                error=(
                    f"resource {resource!r} is out of scope — maximo ingest is "
                    "structured assets/workorders only"
                ),
                detail={"known_resources": list(KNOWN_RESOURCES)},
            )
        return {}

    def _fetch(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        resource = str(payload.get("resource", "")).lower()
        refused = self._require_resource(resource)
        if refused:
            return refused
        if not self._live_configured():
            # Ported from base.py connect(): no live env and no fixture pack
            # (this store ships none) -> ConnectorError. Fail closed here.
            return _envelope(
                "refused",
                error=(
                    "maximo live env is not configured and this store ships no "
                    "maximo fixture pack — refusing to fabricate asset/workorder data"
                ),
                detail={"live_env_keys": list(LIVE_ENV_KEYS), "resource": resource},
            )
        return self._fetch_live(resource, payload)

    def _fetch_live(self, resource: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Ported from base.py BaseConnector.fetch_live.
        import httpx

        params = {k: v for k, v in (payload.get("params") or {}).items()}
        try:
            resp = httpx.get(
                self.live_url(resource),
                headers=self.live_headers(),
                params=params,
                timeout=20,
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return _envelope(
                "error",
                error=f"maximo live fetch failed: {exc}",
                detail={"resource": resource, "url": self.live_url(resource)},
            )
        return _envelope("ok", {"mode": "live", "resource": resource, "data": resp.json()})

    def _guard_source(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Ported from hotelops reasoning/guard.py guard_request(source_system=...):
        # the connector itself must never claim a forbidden source.
        claimed = str(payload.get("source_system", "")).strip().lower()
        if claimed in FORBIDDEN_SOURCES:
            return _envelope(
                "refused",
                error=(
                    f"source system {claimed!r} is out of scope — Aconex/Procore/BIM "
                    "parse is not part of maximo ingest"
                ),
                detail={"code": "construction_pm_out_of_scope"},
            )
        return {}

    def _normalise(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        resource = str(payload.get("resource", "")).lower()
        refused = self._require_resource(resource)
        if refused:
            return refused
        guard = self._guard_source(payload)
        if guard:
            return guard
        raw = payload.get("raw")
        if raw is None:
            return _envelope(
                "refused",
                error="normalise requires 'raw' data (or use ingest to fetch live)",
                detail={"resource": resource},
            )
        if resource == "assets":
            records = raw.get("records", raw if isinstance(raw, list) else [raw])
            if not isinstance(records, list):
                return _envelope("error", error="assets raw data must be a list or {records: [...]}")
            for row in records:
                src = str(row.get("source_system") or "maximo").lower()
                if src in FORBIDDEN_SOURCES:
                    # Ported from maximo.py normalise out-of-scope guard.
                    return _envelope(
                        "refused",
                        error=f"Asset {row.get('asset_id')} source {src} is out of scope",
                        detail={"asset_id": row.get("asset_id"), "source_system": src},
                    )
            events = [
                {
                    "topic": "ops.engineering.asset",
                    "surface": "ops",
                    "source": "maximo_cmms",
                    "payload": {
                        "asset_id": row.get("asset_id") or row.get("id"),
                        "asset_type": row.get("asset_type"),
                        "serial_number": row.get("serial_number"),
                        "location": row.get("location"),
                        "evidence_class": row.get("evidence_class"),
                        "statutory_flag": row.get("statutory_flag", False),
                        "source_system": row.get("source_system", "maximo"),
                    },
                    "evidence_class": row.get("evidence_class"),
                }
                for row in records
            ]
        else:
            records = raw.get("records", raw if isinstance(raw, list) else [raw])
            if not isinstance(records, list):
                return _envelope("error", error="workorders raw data must be a list or {records: [...]}")
            events = [
                {
                    "topic": "ops.cmms.workorder",
                    "surface": "ops",
                    "source": "maximo_cmms",
                    "payload": {
                        "wo": row.get("wo") or row.get("id"),
                        "asset_id": row.get("asset_id"),
                        "status": row.get("status"),
                    },
                }
                for row in records
            ]
        return _envelope("ok", {
            "resource": resource,
            "emitted": len(events),
            "events": events,
        })

    def _ingest(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        resource = str(payload.get("resource", "")).lower()
        refused = self._require_resource(resource)
        if refused:
            return refused
        guard = self._guard_source(payload)
        if guard:
            return guard
        raw = payload.get("raw")
        if raw is None:
            fetched = self._fetch(payload)
            if fetched["status"] != "ok":
                return fetched
            raw = fetched["result"]["data"]
        normalised = self._normalise({"resource": resource, "raw": raw, **payload})
        if normalised["status"] != "ok":
            return normalised
        events = normalised["result"]["events"]
        # Ported from maximo.py ingest: fetch -> normalise -> emit. The
        # hotelops bus is not present in this store; events are returned.
        return _envelope("ok", {
            "connector": "maximo",
            "mode": "live" if raw is None else "raw",
            "resource": resource,
            "emitted": len(events),
            "events": events,
        })
