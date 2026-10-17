"""Shared dataclasses for hotel-management-domain code.

Single source of truth for shapes used by ``HotelBlockV2`` and
``HotelManagementContainer``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class HotelEntity:
    """A hotel-domain entity extracted from document text."""

    type: str
    value: str
    confidence: float = 1.0
    context: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HotelMetric:
    """A hospitality KPI or formula result."""

    name: str
    value: Optional[float]
    inputs: Dict[str, Any] = field(default_factory=dict)
    unit: str = ""
    confidence: float = 1.0
    error: Optional[str] = None


@dataclass
class ComplianceFlag:
    """A compliance/regulatory mention detected in hotel text."""

    regulation: str
    detected: bool
    keywords_found: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class RiskScore:
    """A qualitative operations risk score with supporting evidence."""

    category: str
    score: float
    level: str
    indicators: List[str] = field(default_factory=list)
    confidence: float = 0.0
