"""Insurance Container - insurance domain container v1.0.

Wraps InsuranceBlockV2 and routes domain actions. Accepts user custom rules
injection through params["custom_rules"].
"""

import logging
from typing import Any, Callable, Dict

from app.containers.base import DomainContainer

logger = logging.getLogger(__name__)


class InsuranceContainer(DomainContainer):
    """
    Insurance Container: insurance document analysis, entity extraction,
    metrics, compliance checks, and risk scoring.
    """

    name = "insurance"
    version = "1.0"
    description = "Insurance document analysis, compliance, and risk scoring"
    layer = 3
    tags = ["domain", "container", "insurance"]
    requires = ["insurance_v2"]

    default_config = {
        "confidence_threshold": 0.85,
    }

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste insurance document text or chain from PDF/OCR...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "loss_ratio", "type": "number", "label": "Loss Ratio %"},
                {"name": "combined_ratio", "type": "number", "label": "Combined Ratio %"},
                {"name": "rate_on_line", "type": "number", "label": "Rate on Line %"},
                {"name": "retention_ratio", "type": "number", "label": "Retention Ratio %"},
                {"name": "underwriting_risk", "type": "number", "label": "Underwriting Risk"},
                {"name": "fraud_risk", "type": "number", "label": "Fraud Risk"},
                {"name": "catastrophe_risk", "type": "number", "label": "Catastrophe Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze Policy", "prompt": "Analyze this insurance policy"},
            {"icon": "🏛️", "label": "Check Solvency Compliance", "prompt": "Check this document for solvency compliance"},
            {"icon": "⚠️", "label": "Score Insurance Risks", "prompt": "Score insurance risks for this document"},
            {"icon": "🔍", "label": "Extract Coverage & Limits", "prompt": "Extract coverage and limits from this document"},
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
        """Run full InsuranceBlockV2 analysis."""
        block = self._resolve_block("insurance_v2")
        if block is None:
            return {"status": "error", "error": "%s_v2 block unavailable" % self.name}
        return await block.process(input_data, params)

    async def _extract_entities(self, input_data: Any, params: Dict) -> Dict:
        """Extract insurance entities only."""
        result = await self._analyze(input_data, params)
        if result.get("status") == "error":
            return result
        return {
            "status": "success",
            "entities": result.get("entities", {}),
            "confidence": result.get("confidence", 0),
        }

    async def _calculate_metrics(self, input_data: Any, params: Dict) -> Dict:
        """Calculate insurance metrics only."""
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
        """Score insurance risks only."""
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
