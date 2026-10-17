"""Shared dataclasses for supply_chain-domain code."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SupplyChainEntity:
    """A supply_chain-domain entity extracted from document text."""
    type: str
    value: str
    confidence: float = 1.0
    context: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SupplyChainMetric:
    """A structured supply_chain metric/formula result item."""
    name: str
    value: Any
    inputs: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    error: Optional[str] = None


@dataclass
class ComplianceFlag:
    """A compliance/regulatory mention detected in text."""
    regulation: str
    detected: bool
    keywords_found: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class RiskScore:
    """A qualitative risk score with supporting evidence."""
    category: str
    score: float
    level: str
    indicators: List[str] = field(default_factory=list)
    confidence: float = 0.0
