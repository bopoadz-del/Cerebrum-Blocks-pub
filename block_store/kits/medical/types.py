"""Medical & Healthcare Suite domain types — FHIR models and clinical events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Re-export platform FHIR models for kit consumers
from app.core.connector_events import (  # noqa: F401
    FHIRHumanName,
    FHIRReference,
    MedicationRequest,
    Observation,
    Patient,
)


@dataclass
class ClinicalAlert:
    """Lightweight clinical trigger payload."""

    alert_type: str
    patient_id: Optional[str] = None
    severity: str = "medium"
    summary: str = ""
    fhir_resource: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EHRFetchResult:
    resource_type: str
    count: int
    resources: List[Dict[str, Any]] = field(default_factory=list)
