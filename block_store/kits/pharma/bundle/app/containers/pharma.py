"""Pharma Container - pharma domain container v1.0.

Wraps PharmaBlockV2 and routes domain actions. Accepts user custom rules
injection through params["custom_rules"].
"""

import logging
from typing import Any, Callable, Dict

from app.containers.base import DomainContainer

logger = logging.getLogger(__name__)


class PharmaContainer(DomainContainer):
    """
    Pharma Container: pharma document analysis, entity extraction,
    metrics, compliance checks, and risk scoring.
    """

    name = "pharma"
    version = "1.0"
    description = "Pharma document analysis, compliance, and risk scoring"
    layer = 3
    tags = ["domain", "container", "pharma"]
    requires = ["pharma_v2"]

    default_config = {
        "confidence_threshold": 0.85,
    }

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste pharma document text or chain from PDF/OCR...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "batch_yield", "type": "number", "label": "Batch Yield %"},
                {"name": "assay_purity", "type": "number", "label": "Assay Purity %"},
                {"name": "dissolution_rate", "type": "number", "label": "Dissolution Rate %"},
                {"name": "shelf_life", "type": "number", "label": "Shelf Life (mo)"},
                {"name": "batch_failure_risk", "type": "number", "label": "Batch Failure Risk"},
                {"name": "regulatory_action_risk", "type": "number", "label": "Regulatory Action Risk"},
                {"name": "patient_safety_risk", "type": "number", "label": "Patient Safety Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze Batch Record", "prompt": "Analyze this batch record"},
            {"icon": "🏭", "label": "Check GMP Compliance", "prompt": "Check this document for GMP compliance"},
            {"icon": "⚠️", "label": "Score Pharma Risks", "prompt": "Score pharmaceutical risks for this document"},
            {"icon": "🔍", "label": "Extract Drug Entities", "prompt": "Extract drug entities from this document"},
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
        """Run full PharmaBlockV2 analysis."""
        block = self._resolve_block("pharma_v2")
        if block is None:
            return {"status": "error", "error": "%s_v2 block unavailable" % self.name}
        return await block.process(input_data, params)

    async def _extract_entities(self, input_data: Any, params: Dict) -> Dict:
        """Extract pharma entities only."""
        result = await self._analyze(input_data, params)
        if result.get("status") == "error":
            return result
        return {
            "status": "success",
            "entities": result.get("entities", {}),
            "confidence": result.get("confidence", 0),
        }

    async def _calculate_metrics(self, input_data: Any, params: Dict) -> Dict:
        """Calculate pharma metrics only."""
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
        """Score pharma risks only."""
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
