"""SEC EDGAR connector stub — inherits BaseConnector."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from app.blocks.core.base_connector import BaseConnector
from app.core.connector_events import ConnectorEvent


class SecEdgarConnectorBlock(BaseConnector):
    """Stub for SEC EDGAR filings search (requires SEC_USER_AGENT)."""

    name = "sec_edgar_connector"
    version = "0.1.0-skeleton"
    description = "SEC EDGAR filings connector (stub)"
    layer = 3
    tags = ["finance", "connector", "sec", "edgar", "filings", "stub"]
    connector_source = "sec_edgar"

    default_config = {
        "sec_user_agent": os.getenv("SEC_USER_AGENT", ""),
        "sec_base_url": os.getenv("SEC_BASE_URL", "https://data.sec.gov"),
        "timeout_seconds": 30,
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"cik": "0000320193", "form_type": "10-K"}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "event", "type": "json", "label": "Connector Event"},
                {"name": "filings", "type": "json", "label": "Filings"},
            ],
        },
        "params": [
            {"name": "action", "type": "select", "label": "Action", "options": ["fetch", "auth", "health"], "default": "fetch"},
            {"name": "cik", "type": "text", "label": "CIK"},
            {"name": "form_type", "type": "text", "label": "Form Type"},
        ],
        "quick_actions": [
            {"icon": "📄", "label": "Fetch SEC filings", "prompt": "Fetch SEC EDGAR filings by CIK"},
        ],
    }

    def _user_agent(self) -> str:
        return self.config.get("sec_user_agent") or os.getenv("SEC_USER_AGENT", "")

    def _base_url(self) -> str:
        return (
            self.config.get("sec_base_url")
            or os.getenv("SEC_BASE_URL", "https://data.sec.gov")
        ).rstrip("/")

    async def authenticate(self) -> Dict[str, Any]:
        ua = self._user_agent()
        if not ua:
            return {
                "authenticated": False,
                "error": "SEC_USER_AGENT required (SEC mandates contact info in User-Agent)",
            }
        return {"authenticated": True, "method": "user_agent", "base_url": self._base_url()}

    async def fetch_raw(self, input_data: Any, params: Dict) -> Any:
        data = input_data if isinstance(input_data, dict) else {}
        cik = params.get("cik") or data.get("cik")
        form_type = params.get("form_type") or data.get("form_type", "10-K")
        if not cik:
            raise ValueError("cik is required for SEC EDGAR fetch")

        ua = self._user_agent()
        if not ua:
            raise ValueError("SEC_USER_AGENT not configured")

        cik_padded = str(cik).zfill(10)
        base = self._base_url()
        url = f"{base}/submissions/CIK{cik_padded}.json"
        headers = {"User-Agent": ua, "Accept": "application/json"}
        timeout = float(self.config.get("timeout_seconds", 30))

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                return {
                    "stub": True,
                    "cik": cik,
                    "form_type": form_type,
                    "filings": [
                        {
                            "accession_number": "0000320193-24-000001",
                            "form": form_type,
                            "filing_date": "2024-01-01",
                            "primary_document": "stub-10k.htm",
                        }
                    ],
                    "message": "SEC EDGAR endpoint unavailable — returning stub response",
                }
            resp.raise_for_status()
            body = resp.json()
            recent = body.get("filings", {}).get("recent", {})
            filings = []
            if recent:
                forms = recent.get("form", [])
                dates = recent.get("filingDate", [])
                accessions = recent.get("accessionNumber", [])
                for i, form in enumerate(forms):
                    if form_type and form != form_type:
                        continue
                    filings.append({
                        "form": form,
                        "filing_date": dates[i] if i < len(dates) else None,
                        "accession_number": accessions[i] if i < len(accessions) else None,
                    })
            return {"cik": cik, "form_type": form_type, "filings": filings, "raw": body}

    def normalize(
        self, raw: Any, params: Optional[Dict] = None, input_data: Any = None
    ) -> ConnectorEvent:
        data = input_data if isinstance(input_data, dict) else {}
        cik = (params or {}).get("cik") or data.get("cik", "")
        filings = []
        if isinstance(raw, dict):
            filings = raw.get("filings") or []
        return ConnectorEvent(
            source=self.connector_source,
            event_type="sec.filings.fetched",
            payload=raw if isinstance(raw, dict) else {"data": raw},
            normalized_data={
                "cik": cik,
                "count": len(filings) if isinstance(filings, list) else 0,
                "filings": filings,
            },
            tags=["finance", "sec", "edgar"],
        )
