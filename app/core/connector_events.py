"""Connector event models — normalized payloads for video, medical, and IoT sources."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AnomalySeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ZoneOccupancy(BaseModel):
    zone_id: str
    label: Optional[str] = None
    count: int = 0
    capacity: Optional[int] = None
    occupancy_pct: Optional[float] = None


class QueueInfo(BaseModel):
    queue_id: str
    label: Optional[str] = None
    length: int = 0
    avg_wait_seconds: Optional[float] = None
    threshold_exceeded: bool = False


class Anomaly(BaseModel):
    anomaly_id: str = Field(default_factory=lambda: str(uuid4())[:12])
    anomaly_type: str
    severity: AnomalySeverity = AnomalySeverity.MEDIUM
    zone_id: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    description: Optional[str] = None
    timestamp: datetime = Field(default_factory=_utc_now)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VideoMetadata(BaseModel):
    source_id: str
    camera_id: str
    timestamp: datetime = Field(default_factory=_utc_now)
    frame_id: Optional[str] = None
    zones: List[ZoneOccupancy] = Field(default_factory=list)
    queues: List[QueueInfo] = Field(default_factory=list)
    anomalies: List[Anomaly] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: Any) -> Any:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class ConnectorEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4())[:12])
    source: str
    event_type: str
    timestamp: datetime = Field(default_factory=_utc_now)
    payload: Dict[str, Any] = Field(default_factory=dict)
    normalized_data: Optional[Dict[str, Any]] = None
    tags: List[str] = Field(default_factory=list)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: Any) -> Any:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


# ── FHIR-lite models (medical EHR connector) ──────────────────────────────────


class FHIRReference(BaseModel):
    reference: Optional[str] = None
    display: Optional[str] = None


class FHIRHumanName(BaseModel):
    use: Optional[str] = None
    family: Optional[str] = None
    given: List[str] = Field(default_factory=list)
    text: Optional[str] = None


class Patient(BaseModel):
    # Real FHIR payloads are camelCase (birthDate, effectiveDateTime...);
    # accept both camelCase input and snake_case by name.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    resource_type: str = "Patient"
    id: Optional[str] = None
    active: Optional[bool] = None
    name: List[FHIRHumanName] = Field(default_factory=list)
    birth_date: Optional[str] = None
    gender: Optional[str] = None
    identifier: List[Dict[str, Any]] = Field(default_factory=list)


class Observation(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    resource_type: str = "Observation"
    id: Optional[str] = None
    status: Optional[str] = None
    code: Optional[Dict[str, Any]] = None
    subject: Optional[FHIRReference] = None
    effective_date_time: Optional[str] = None
    value_quantity: Optional[Dict[str, Any]] = None
    value_string: Optional[str] = None
    component: List[Dict[str, Any]] = Field(default_factory=list)


class MedicationRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    resource_type: str = "MedicationRequest"
    id: Optional[str] = None
    status: Optional[str] = None
    intent: Optional[str] = None
    subject: Optional[FHIRReference] = None
    medication_codeable_concept: Optional[Dict[str, Any]] = None
    authored_on: Optional[str] = None
    dosage_instruction: List[Dict[str, Any]] = Field(default_factory=list)
