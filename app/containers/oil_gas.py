"""OilGas Container - oil_gas domain container v1.0.

Wraps OilGasBlockV2 and routes domain actions. Accepts user custom rules
injection through params["custom_rules"].
"""

import logging
from typing import Any, Callable, Dict

from app.containers.base import DomainContainer

logger = logging.getLogger(__name__)


class OilGasContainer(DomainContainer):
    """
    OilGas Container: oil_gas document analysis, entity extraction,
    metrics, compliance checks, and risk scoring.
    """

    name = "oil_gas"
    version = "1.0"
    description = "OilGas document analysis, compliance, and risk scoring"
    layer = 3
    tags = ["domain", "container", "oil_gas"]
    requires = ["oil_gas_v2"]

    default_config = {
        "confidence_threshold": 0.85,
    }

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste oil_gas document text or chain from PDF/OCR...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "rop", "type": "number", "label": "ROP"},
                {"name": "water_cut", "type": "number", "label": "Water Cut %"},
                {"name": "gas_oil_ratio", "type": "number", "label": "GOR"},
                {"name": "recovery_factor", "type": "number", "label": "Recovery Factor %"},
                {"name": "well_control_risk", "type": "number", "label": "Well Control Risk"},
                {"name": "environmental_risk", "type": "number", "label": "Environmental Risk"},
                {"name": "regulatory_risk", "type": "number", "label": "Regulatory Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze Well Log", "prompt": "Analyze this well log"},
            {"icon": "🛢️", "label": "Check BSEE Compliance", "prompt": "Check this document for BSEE compliance"},
            {"icon": "⚠️", "label": "Score Oil & Gas Risks", "prompt": "Score oil and gas risks for this document"},
            {"icon": "🔍", "label": "Extract Wells & Formations", "prompt": "Extract wells and formations from this document"},
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
        """Run full OilGasBlockV2 analysis."""
        block = self._resolve_block("oil_gas_v2")
        if block is None:
            return {"status": "error", "error": "%s_v2 block unavailable" % self.name}
        return await block.process(input_data, params)

    async def _extract_entities(self, input_data: Any, params: Dict) -> Dict:
        """Extract oil_gas entities only."""
        result = await self._analyze(input_data, params)
        if result.get("status") == "error":
            return result
        return {
            "status": "success",
            "entities": result.get("entities", {}),
            "confidence": result.get("confidence", 0),
        }

    async def _calculate_metrics(self, input_data: Any, params: Dict) -> Dict:
        """Calculate oil_gas metrics only."""
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
        """Score oil_gas risks only."""
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
