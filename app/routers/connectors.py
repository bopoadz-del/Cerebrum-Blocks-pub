"""Connector routers — direct invoke endpoints for domain connectors."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.http_errors import classify_block_error
from app.dependencies import get_block_instance, require_api_key

router = APIRouter(prefix="/v1/connectors", tags=["connectors"])


class EHRFetchRequest(BaseModel):
    resource: str = Field(default="Patient", description="Patient | Observation | MedicationRequest")
    resource_id: Optional[str] = None
    patient_id: Optional[str] = None
    query: Optional[Dict[str, Any]] = None
    action: str = "fetch"


@router.post("/medical/ehr")
async def medical_ehr_invoke(
    request: EHRFetchRequest,
    auth: dict = Depends(require_api_key),
):
    """Direct invoke for the FHIR medical EHR connector."""
    block = get_block_instance("medical_ehr_connector")
    params = {"action": request.action, "resource": request.resource}
    data = request.model_dump(exclude_none=True)
    result = await block.process(data, params)

    if result.get("status") == "error":
        err = result.get("error", "EHR fetch failed")
        raise HTTPException(status_code=classify_block_error(result), detail=err)

    return result


class HotelAnalyzeRequest(BaseModel):
    text: str = Field(..., description="Hotel document text to analyze")
    document_type: Optional[str] = None
    custom_rules: Optional[Dict[str, Any]] = None


class OperaFetchRequest(BaseModel):
    resource: str = Field(default="reservations", description="reservations | folios | rooms | profiles")
    action: str = "fetch"


@router.post("/hotel/analyze")
async def hotel_analyze_invoke(
    request: HotelAnalyzeRequest,
    auth: dict = Depends(require_api_key),
):
    """Direct invoke for the hotel_v2 document analysis (ADR/RevPAR/GOPPAR/risk)."""
    from app.blocks.hotel_v2 import HotelBlockV2

    block = HotelBlockV2()
    params: Dict[str, Any] = {}
    if request.document_type:
        params["document_type"] = request.document_type
    if request.custom_rules is not None:
        params["custom_rules"] = request.custom_rules
    result = await block.process({"text": request.text}, params)
    return result


@router.post("/hotel/opera")
async def hotel_opera_invoke(
    request: OperaFetchRequest,
    auth: dict = Depends(require_api_key),
):
    """Direct invoke for the Opera PMS connector (fail-closed without live config)."""
    from block_store.kits.hotel_management.blocks.opera_connector import OperaConnectorBlock

    block = OperaConnectorBlock()
    params = {"action": request.action, "resource": request.resource}
    result = await block.process({"resource": request.resource}, params)

    if result.get("status") == "error":
        auth = result.get("auth") or {}
        err = auth.get("refusal") or result.get("error") or "Opera fetch failed"
        raise HTTPException(status_code=classify_block_error(result), detail=err)

    return result
