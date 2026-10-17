"""HR Container - hr domain container v1.0.

Wraps HRBlockV2 and routes domain actions. Accepts user custom rules
injection through params["custom_rules"].
"""

import logging
from typing import Any, Callable, Dict

from app.containers.base import DomainContainer

logger = logging.getLogger(__name__)


class HRContainer(DomainContainer):
    """
    HR Container: hr document analysis, entity extraction,
    metrics, compliance checks, and risk scoring.
    """

    name = "hr"
    version = "1.0"
    description = "HR document analysis, compliance, and risk scoring"
    layer = 3
    tags = ["domain", "container", "hr"]
    requires = ["hr_v2"]

    default_config = {
        "confidence_threshold": 0.85,
    }

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste hr document text or chain from PDF/OCR...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "time_to_fill", "type": "number", "label": "Time to Fill (days)"},
                {"name": "cost_per_hire", "type": "number", "label": "Cost per Hire"},
                {"name": "turnover_rate", "type": "number", "label": "Turnover Rate %"},
                {"name": "offer_acceptance_rate", "type": "number", "label": "Offer Acceptance %"},
                {"name": "litigation_risk", "type": "number", "label": "Litigation Risk"},
                {"name": "talent_retention_risk", "type": "number", "label": "Talent Retention Risk"},
                {"name": "compliance_risk", "type": "number", "label": "Compliance Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze Employment Contract", "prompt": "Analyze this employment contract"},
            {"icon": "⚖️", "label": "Check EEO Compliance", "prompt": "Check this document for EEO compliance"},
            {"icon": "⚠️", "label": "Score HR Risks", "prompt": "Score HR risks for this document"},
            {"icon": "🔍", "label": "Extract Salaries & Dates", "prompt": "Extract salaries and dates from this document"},
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
        """Run full HRBlockV2 analysis."""
        block = self._resolve_block("hr_v2")
        if block is None:
            return {"status": "error", "error": "%s_v2 block unavailable" % self.name}
        return await block.process(input_data, params)

    async def _extract_entities(self, input_data: Any, params: Dict) -> Dict:
        """Extract hr entities only."""
        result = await self._analyze(input_data, params)
        if result.get("status") == "error":
            return result
        return {
            "status": "success",
            "entities": result.get("entities", {}),
            "confidence": result.get("confidence", 0),
        }

    async def _calculate_metrics(self, input_data: Any, params: Dict) -> Dict:
        """Calculate hr metrics only."""
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
        """Score hr risks only."""
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
