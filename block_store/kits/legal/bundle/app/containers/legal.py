"""Legal Container - Legal domain container v1.0.

Wraps LegalBlockV2 and routes domain actions. Accepts user custom rules
injection through params["custom_rules"].
"""

import logging
from typing import Any, Callable, Dict

from app.containers.base import DomainContainer

logger = logging.getLogger(__name__)


class LegalContainer(DomainContainer):
    """
    Legal Container: Legal document analysis, entity extraction,
    legal analysis, compliance checks, and risk scoring.
    """

    name = "legal"
    version = "1.0"
    description = "Legal document analysis, compliance, and risk scoring"
    layer = 3
    tags = ["domain", "container", "legal", "law"]
    requires = ["legal_v2"]

    default_config = {
        "confidence_threshold": 0.85,
    }

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste legal document text or chain from PDF/OCR...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "contract_value", "type": "number", "label": "Contract Value"},
                {"name": "limitation_periods", "type": "number", "label": "Limitation Periods"},
                {"name": "termination_provisions", "type": "number", "label": "Termination Provisions"},
                {"name": "litigation_risk", "type": "number", "label": "Litigation Risk"},
                {"name": "regulatory_risk", "type": "number", "label": "Regulatory Risk"},
                {"name": "financial_risk", "type": "number", "label": "Financial Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze Contract", "prompt": "Analyze this legal contract"},
            {"icon": "⚖️", "label": "Check Compliance", "prompt": "Check this document for regulatory compliance"},
            {"icon": "⚠️", "label": "Score Legal Risks", "prompt": "Score legal risks for this document"},
            {"icon": "🔍", "label": "Extract Parties & Counsel", "prompt": "Extract parties, counsel, courts, and citations from this document"},
        ],
    }

    def get_actions(self) -> Dict[str, Callable]:
        """Return action name → handler mapping."""
        return {
            "analyze": self._analyze,
            "extract_entities": self._extract_entities,
            "legal_analysis": self._legal_analysis,
            "check_compliance": self._check_compliance,
            "score_risk": self._score_risk,
            "health": self._health,
        }

    # ------------------------------------------------------------------
    # HANDLERS
    # ------------------------------------------------------------------

    async def _analyze(self, input_data: Any, params: Dict) -> Dict:
        """Run full LegalBlockV2 analysis."""
        block = self._resolve_block("legal_v2")
        if block is None:
            return {"status": "error", "error": "legal_v2 block unavailable"}
        return await block.process(input_data, params)

    async def _extract_entities(self, input_data: Any, params: Dict) -> Dict:
        """Extract legal entities only."""
        result = await self._analyze(input_data, params)
        if result.get("status") == "error":
            return result
        return {
            "status": "success",
            "entities": result.get("entities", {}),
            "confidence": result.get("confidence", 0),
        }

    async def _legal_analysis(self, input_data: Any, params: Dict) -> Dict:
        """Run legal analysis only."""
        result = await self._analyze(input_data, params)
        if result.get("status") == "error":
            return result
        return {
            "status": "success",
            "legal_analysis": result.get("legal_analysis", {}),
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
        """Score legal risks only."""
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
