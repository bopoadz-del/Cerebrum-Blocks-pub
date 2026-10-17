"""Power BI connector — export, publish/refresh stubs, embed placeholder.

Ported from C:\\Users\\<owner>\\<private-product>\\backend\\app\\retailops\\
integrations\\connectors\\power_bi.py (PowerBiConnector) and
integrations\\mock_data.py (power_bi_kpi_rows + STORE_IDS) /
integrations\\base.py (deterministic_rng).

Mock-functional (per the donor's own labeling): the KPI dataset pull and
CSV/XLSX export are real, working code paths — no fabricated files, just
genuinely generated CSV/XLSX bytes from deterministic fictional KPI rows
(or caller-supplied rows). "Publish dataset" and "refresh semantic model"
stay honest stubs (refused, per the donor's not_implemented responses); the
embed dashboard URL is an explicit placeholder, never a fabricated real
link. When all four RETAILOPS_POWERBI_* values are configured,
test_connection performs a real Azure AD client-credentials token request +
a real Power BI REST call to verify workspace access. No credentials are
hardcoded; nothing is attempted without them.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "power_bi_connector",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


_AAD_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_POWERBI_API = "https://api.powerbi.com/v1.0/myorg"
_POWERBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"

ENV_KEYS = (
    "RETAILOPS_POWERBI_TENANT_ID",
    "RETAILOPS_POWERBI_CLIENT_ID",
    "RETAILOPS_POWERBI_CLIENT_SECRET",
    "RETAILOPS_POWERBI_WORKSPACE_ID",
)

# Ported from <client> mock_data.py.
STORE_IDS = [f"ST-{n:03d}" for n in (101, 102, 103, 104, 105)]


def deterministic_rng(*parts: str) -> random.Random:
    """Ported from <client> integrations/base.py deterministic_rng."""
    seed_material = "|".join(parts).encode("utf-8")
    seed = int(hashlib.sha256(seed_material).hexdigest(), 16)
    return random.Random(seed)


def power_bi_kpi_rows(seed_key: str, count: int = 14) -> List[Dict[str, Any]]:
    """Ported from <client> integrations/mock_data.py power_bi_kpi_rows.

    Fictional daily KPI rows for the Power BI export stub — deterministic
    fiction, clearly labeled, never presented as live data.
    """
    rng = deterministic_rng("powerbi", seed_key)
    rows: List[Dict[str, Any]] = []
    for i in range(count):
        store = rng.choice(STORE_IDS)
        rows.append({
            "date": f"2026-07-{(i % 28) + 1:02d}",
            "store_id": store,
            "total_sales": round(rng.uniform(4000, 22000), 2),
            "transaction_count": rng.randint(120, 900),
            "stockout_events": rng.randint(0, 6),
            "supplier_delay_events": rng.randint(0, 3),
        })
    return rows


class PowerBiConnectorBlock(UniversalBlock):
    """Power BI KPI export connector — mock-functional port from <client>."""

    name = "power_bi_connector"
    version = "1.0.0"
    description = (
        "mock-functional — Power BI connector ported from "
        "C:\\Users\\<owner>\\<private-product>\\backend\\app\\retailops\\"
        "integrations\\connectors\\power_bi.py (+ mock_data.py, base.py). KPI "
        "dataset pull and CSV/XLSX export are real working paths on "
        "deterministic fictional rows (never live data); publish_dataset and "
        "refresh_semantic_model are honest not-implemented stubs (refused); "
        "embed URL is an explicit placeholder. With all RETAILOPS_POWERBI_* "
        "configured, test_connection performs a real Azure AD token request "
        "and Power BI workspace check."
    )
    layer = 2
    tags = ["connector", "power-bi", "analytics", "export", "mock-functional"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"action": "pull", "cursor": "default"}',
            "multiline": True,
        },
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}]},
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        # Donor reads os.getenv; block config may override per-key.
        self.tenant_id = str(
            self.config.get("RETAILOPS_POWERBI_TENANT_ID")
            or os.getenv("RETAILOPS_POWERBI_TENANT_ID", "")
        )
        self.client_id = str(
            self.config.get("RETAILOPS_POWERBI_CLIENT_ID")
            or os.getenv("RETAILOPS_POWERBI_CLIENT_ID", "")
        )
        self.client_secret = str(
            self.config.get("RETAILOPS_POWERBI_CLIENT_SECRET")
            or os.getenv("RETAILOPS_POWERBI_CLIENT_SECRET", "")
        )
        self.workspace_id = str(
            self.config.get("RETAILOPS_POWERBI_WORKSPACE_ID")
            or os.getenv("RETAILOPS_POWERBI_WORKSPACE_ID", "")
        )

    def available(self) -> bool:
        # Ported from power_bi.py PowerBiConnector.available.
        return bool(self.tenant_id and self.client_id and self.client_secret and self.workspace_id)

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "status")).lower()
        try:
            if action == "status":
                return _envelope("ok", {
                    "connector_id": "power_bi",
                    "configured": self.available(),
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "source": "mock" if not self.available() else "configured-live-capable",
                })
            if action == "capabilities":
                return _envelope("ok", {
                    "supported_actions": [
                        "status", "capabilities", "test_connection", "pull",
                        "normalize", "export_csv", "export_xlsx",
                        "publish_dataset", "refresh_semantic_model", "get_embed_url",
                    ],
                    "implemented": ["export_csv", "export_xlsx", "kpi_dataset_pull", "normalize", "test_connection"],
                    "not_implemented": ["publish_dataset", "refresh_semantic_model"],
                    "placeholder": ["get_embed_url"],
                })
            if action == "test_connection":
                return await self._test_connection()
            if action == "pull":
                return await self._pull(payload)
            if action == "normalize":
                return await self._normalize(payload)
            if action == "export_csv":
                return self._export_csv(payload)
            if action == "export_xlsx":
                return self._export_xlsx(payload)
            if action in ("publish_dataset", "refresh_semantic_model"):
                return self._not_implemented(action)
            if action == "get_embed_url":
                return _envelope("ok", {
                    "status": "placeholder",
                    "embed_url": "https://app.powerbi.com/reportEmbed?reportId=PLACEHOLDER",
                    "message": "Placeholder embed URL — no live dashboard is provisioned in this pilot.",
                })
            return _envelope(
                "error",
                error=f"unknown action: {action}",
                detail={"known": [
                    "status", "capabilities", "test_connection", "pull",
                    "normalize", "export_csv", "export_xlsx",
                    "publish_dataset", "refresh_semantic_model", "get_embed_url",
                ]},
            )
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    async def _acquire_token(self) -> str:
        # Ported from power_bi.py PowerBiConnector._acquire_token.
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
                    raise RuntimeError("Azure AD token response missing access_token")
                return token
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Azure AD token request failed: {exc}") from exc

    async def _test_connection(self) -> Dict[str, Any]:
        # Ported from power_bi.py PowerBiConnector.test_connection.
        if not self.available():
            return _envelope("ok", {
                "ok": True,
                "status": "mock",
                "message": (
                    "No Power BI workspace configured — CSV/XLSX export works in "
                    "mock mode. Set RETAILOPS_POWERBI_TENANT_ID/_CLIENT_ID/"
                    "_CLIENT_SECRET/_WORKSPACE_ID for a real connectivity test."
                ),
            })
        import httpx

        try:
            token = await self._acquire_token()
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{_POWERBI_API}/groups/{self.workspace_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
            return _envelope("ok", {
                "ok": True,
                "status": "connected",
                "message": "Power BI workspace reachable.",
            })
        except Exception as exc:  # noqa: BLE001
            return _envelope("ok", {
                "ok": False,
                "status": "error",
                "message": str(exc),
            })

    async def _pull(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Ported from power_bi.py PowerBiConnector.pull.
        seed_key = payload.get("cursor") or payload.get("since") or "default"
        rows = power_bi_kpi_rows(str(seed_key))
        return _envelope("ok", {
            "records": rows,
            "next_cursor": f"powerbi-{seed_key}-next",
            "source": "mock",
        })

    async def _normalize(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Ported from power_bi.py PowerBiConnector.normalize.
        records = payload.get("records") or []
        if not isinstance(records, list):
            return _envelope("error", error="records must be a list")
        return _envelope("ok", {
            "records": [
                {
                    "date": rec.get("date"),
                    "store": rec.get("store_id"),
                    "total_sales": rec.get("total_sales"),
                    "transaction_count": rec.get("transaction_count"),
                    "stockout_events": rec.get("stockout_events"),
                    "supplier_delay_events": rec.get("supplier_delay_events"),
                }
                for rec in records
            ],
        })

    def _not_implemented(self, action: str) -> Dict[str, Any]:
        # Ported from power_bi.py push(): these stay honest stubs.
        if action == "publish_dataset":
            message = (
                "Publishing a KPI dataset to a live Power BI workspace is not "
                "implemented in this pilot. This is an honest stub."
            )
        else:
            message = (
                "Triggering a semantic model refresh is not implemented in "
                "this pilot. This is an honest stub."
            )
        return _envelope("refused", {
            "ok": False,
            "status": "not_implemented",
            "message": message,
        })

    def _rows_for_export(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Ported from power_bi.py PowerBiConnector._rows_for_export.
        rows = payload.get("rows")
        if isinstance(rows, list) and rows:
            return rows
        return power_bi_kpi_rows(str(payload.get("cursor") or "export"))

    def _export_csv(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Ported from power_bi.py PowerBiConnector._export_csv.
        rows = self._rows_for_export(payload)
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return _envelope("ok", {
            "ok": True,
            "status": "exported",
            "filename": "retailops-kpi-export.csv",
            "content_type": "text/csv",
            "content_base64": base64.b64encode(buf.getvalue().encode("utf-8")).decode("ascii"),
            "row_count": len(rows),
        })

    def _export_xlsx(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Ported from power_bi.py PowerBiConnector._export_xlsx.
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
        return _envelope("ok", {
            "ok": True,
            "status": "exported",
            "filename": "retailops-kpi-export.xlsx",
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "content_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "row_count": len(rows),
        })
