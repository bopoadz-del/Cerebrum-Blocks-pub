"""Medical EHR connector — FHIR R4 fetch via httpx with env-based auth."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

from app.blocks.core.base_connector import BaseConnector
from app.core.connector_events import (
    ConnectorEvent,
    MedicationRequest,
    Observation,
    Patient,
)
from app.core.http_errors import mark_unavailable, UNAVAILABLE


class MedicalEHRConnectorBlock(BaseConnector):
    name = "medical_ehr_connector"
    version = "1.0.0"
    description = "Fetch FHIR Patient, Observation, and MedicationRequest resources from an EHR"
    layer = 2
    tags = ["connector", "medical", "fhir", "ehr", "healthcare"]
    connector_source = "medical_ehr"

    default_config = {
        "fhir_base_url": os.getenv("FHIR_BASE_URL", ""),
        "fhir_access_token": os.getenv("FHIR_ACCESS_TOKEN", ""),
        "fhir_client_id": os.getenv("FHIR_CLIENT_ID", ""),
        "fhir_client_secret": os.getenv("FHIR_CLIENT_SECRET", ""),
        "timeout_seconds": 30,
    }

    _RESOURCE_MODELS = {
        "Patient": Patient,
        "Observation": Observation,
        "MedicationRequest": MedicationRequest,
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"resource": "Patient", "patient_id": "123"}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "event", "type": "json", "label": "Connector Event"},
                {"name": "resources", "type": "json", "label": "FHIR Resources"},
            ],
        },
        "params": [
            {
                "name": "action",
                "type": "select",
                "label": "Action",
                "options": ["fetch", "auth", "health"],
                "default": "fetch",
            },
            {
                "name": "resource",
                "type": "select",
                "label": "FHIR Resource",
                "options": ["Patient", "Observation", "MedicationRequest"],
                "default": "Patient",
            },
            {
                "name": "resource_type",
                "type": "select",
                "label": "Resource type (alias)",
                "options": ["Patient", "Observation", "MedicationRequest"],
                "default": "Observation",
            },
            {
                "name": "patient_id",
                "type": "text",
                "label": "Patient ID",
            },
            {
                "name": "limit",
                "type": "number",
                "label": "Max results",
                "default": 20,
            },
        ],
        "quick_actions": [
            {"icon": "🏥", "label": "Fetch patient", "prompt": "Fetch FHIR Patient by ID"},
        ],
    }

    def _base_url(self) -> str:
        return (
            self.config.get("fhir_base_url")
            or os.getenv("FHIR_BASE_URL", "")
        ).rstrip("/")

    def _token(self) -> str:
        return (
            self.config.get("fhir_access_token")
            or os.getenv("FHIR_ACCESS_TOKEN", "")
        )

    async def authenticate(self) -> Dict[str, Any]:
        base = self._base_url()
        token = self._token()
        if not base:
            return {"authenticated": False, "error": "FHIR_BASE_URL not configured", "error_kind": UNAVAILABLE}
        if token:
            return {"authenticated": True, "method": "bearer_token", "base_url": base}
        client_id = self.config.get("fhir_client_id") or os.getenv("FHIR_CLIENT_ID", "")
        client_secret = self.config.get("fhir_client_secret") or os.getenv("FHIR_CLIENT_SECRET", "")
        if client_id and client_secret:
            return {"authenticated": True, "method": "client_credentials_pending", "base_url": base}
        return {"authenticated": False, "error": "FHIR_ACCESS_TOKEN or client credentials required"}

    async def fetch_raw(self, input_data: Any, params: Dict) -> Any:
        data = input_data if isinstance(input_data, dict) else {}
        resource = (
            params.get("resource")
            or params.get("resource_type")
            or data.get("resource")
            or data.get("resource_type", "Patient")
        )
        resource_id = data.get("resource_id") or data.get("patient_id") or data.get("id")
        query = data.get("query") or params.get("query")
        limit = params.get("limit") or data.get("limit")

        base = self._base_url()
        if not base:
            raise mark_unavailable(ValueError("FHIR_BASE_URL not configured"))

        if resource_id:
            url = f"{base}/{resource}/{resource_id}"
        else:
            url = f"{base}/{resource}"
            if query and isinstance(query, dict):
                pass
            elif data.get("patient_id") and resource != "Patient":
                query = {"subject": f"Patient/{data['patient_id']}"}

        if isinstance(query, dict) and limit is not None:
            query = {**query, "_count": str(limit)}
        elif limit is not None and not query:
            query = {"_count": str(limit)}

        headers = {"Accept": "application/fhir+json"}
        token = self._token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        timeout = float(self.config.get("timeout_seconds", 30))
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers, params=query if isinstance(query, dict) else None)
            resp.raise_for_status()
            return resp.json()

    def normalize(
        self, raw: Any, params: Optional[Dict] = None, input_data: Any = None
    ) -> ConnectorEvent:
        data = input_data if isinstance(input_data, dict) else {}
        resource = (
            (params or {}).get("resource")
            or (params or {}).get("resource_type")
            or data.get("resource")
            or data.get("resource_type", "Patient")
        )
        parsed = self._parse_fhir_bundle(raw, resource)
        return ConnectorEvent(
            source=self.connector_source,
            event_type=f"fhir.{resource.lower()}.fetched",
            payload={"raw": raw if isinstance(raw, dict) else {"data": raw}},
            normalized_data={
                "resource": resource,
                "count": len(parsed),
                "resources": [r.model_dump(mode="json") for r in parsed],
            },
            tags=["medical", "fhir", resource.lower()],
        )

    def _parse_fhir_bundle(self, raw: Any, resource: str) -> List[Any]:
        model = self._RESOURCE_MODELS.get(resource, Patient)
        if not isinstance(raw, dict):
            return []
        if raw.get("resourceType") == "Bundle":
            entries = raw.get("entry", [])
            results = []
            for entry in entries:
                res = entry.get("resource") if isinstance(entry, dict) else None
                if res and res.get("resourceType") == resource:
                    try:
                        results.append(model.model_validate(res))
                    except Exception:
                        continue
            return results
        if raw.get("resourceType") == resource:
            try:
                return [model.model_validate(raw)]
            except Exception:
                return []
        return []
