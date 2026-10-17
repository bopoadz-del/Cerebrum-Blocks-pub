"""Hotel Management Container - Hospitality domain container v1.0.

Wraps HotelBlockV2 and routes domain actions. Accepts user custom rules
injection through params["custom_rules"].
"""

import logging
from typing import Any, Callable, Dict

from app.containers.base import DomainContainer

logger = logging.getLogger(__name__)


class HotelManagementContainer(DomainContainer):
    """
    Hotel Management Container: Hospitality document analysis, entity extraction,
    metrics calculation, compliance checks, and risk scoring.
    """

    name = "hotel_management"
    version = "1.0"
    description = "Hotel management document analysis, metrics, compliance, and risk scoring"
    layer = 3
    tags = ["domain", "container", "hotel", "hospitality"]
    requires = ["hotel_v2"]

    default_config = {
        "confidence_threshold": 0.85,
    }

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste hotel document text or chain from PDF/OCR...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "adr", "type": "number", "label": "ADR", "unit": "$"},
                {"name": "revpar", "type": "number", "label": "RevPAR", "unit": "$"},
                {"name": "occupancy_rate", "type": "percentage", "label": "Occupancy"},
                {"name": "goppar", "type": "number", "label": "GOPPAR", "unit": "$"},
                {"name": "overbooking_risk", "type": "number", "label": "Overbooking Risk"},
                {"name": "revenue_leakage", "type": "number", "label": "Revenue Leakage"},
                {"name": "fraud_risk", "type": "number", "label": "Fraud Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📊", "label": "Analyze Revenue Report", "prompt": "Analyze this hotel revenue report"},
            {"icon": "🧾", "label": "Check Guest Folio", "prompt": "Check this guest folio for charges and discrepancies"},
            {"icon": "⚠️", "label": "Score Operational Risks", "prompt": "Score operational risks for this hotel document"},
            {"icon": "✅", "label": "Check Compliance", "prompt": "Check this hotel document for compliance flags"},
        ],
    }

    def get_actions(self) -> Dict[str, Callable]:
        """Return action name → handler mapping."""
        return {
            "analyze": self._analyze,
            "extract_entities": self._extract_entities,
            "calculate_metrics": self._calculate_metrics,
            "check_compliance": self._check_compliance,
            "score_risk": self._score_risk,
            "health": self._health,
        }

    # ------------------------------------------------------------------
    # HANDLERS
    # ------------------------------------------------------------------

    async def _analyze(self, input_data: Any, params: Dict) -> Dict:
        """Run full HotelBlockV2 analysis."""
        block = self._resolve_block("hotel_v2")
        if block is None:
            return {"status": "error", "error": "hotel_v2 block unavailable"}
        return await block.process(input_data, params)

    async def _extract_entities(self, input_data: Any, params: Dict) -> Dict:
        """Extract hotel entities only."""
        result = await self._analyze(input_data, params)
        if result.get("status") == "error":
            return result
        return {
            "status": "success",
            "entities": result.get("entities", {}),
            "confidence": result.get("confidence", 0),
        }

    async def _calculate_metrics(self, input_data: Any, params: Dict) -> Dict:
        """Calculate hotel metrics only."""
        result = await self._analyze(input_data, params)
        if result.get("status") == "error":
            return result
        return {
            "status": "success",
            "metrics": result.get("metrics", {}),
            "financials": result.get("financials", {}),
            "confidence": result.get("confidence", 0),
        }

    async def _check_compliance(self, input_data: Any, params: Dict) -> Dict:
        """Check compliance flags only."""
        result = await self._analyze(input_data, params)
        if result.get("status") == "error":
            return result
        return {
            "status": "success",
            "compliance_flags": result.get("compliance_flags", {}),
            "custom_rule_hits": result.get("custom_rule_hits", []),
            "confidence": result.get("confidence", 0),
        }

    async def _score_risk(self, input_data: Any, params: Dict) -> Dict:
        """Score hotel operational risks only."""
        result = await self._analyze(input_data, params)
        if result.get("status") == "error":
            return result
        return {
            "status": "success",
            "risk_scores": result.get("risk_scores", {}),
            "confidence": result.get("confidence", 0),
        }

    async def _health(self, input_data: Any, params: Dict) -> Dict:
        """Container health check."""
        return {
            "status": "healthy",
            "container": self.name,
            "version": self.version,
        }
