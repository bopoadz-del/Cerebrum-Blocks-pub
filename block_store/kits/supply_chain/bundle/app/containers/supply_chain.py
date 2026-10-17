"""SupplyChain Container - supply_chain domain container v1.0.

Wraps SupplyChainBlockV2 and routes domain actions. Accepts user custom rules
injection through params["custom_rules"].
"""

import logging
from typing import Any, Callable, Dict

from app.containers.base import DomainContainer

logger = logging.getLogger(__name__)


class SupplyChainContainer(DomainContainer):
    """
    SupplyChain Container: supply_chain document analysis, entity extraction,
    metrics, compliance checks, and risk scoring.
    """

    name = "supply_chain"
    version = "1.0"
    description = "SupplyChain document analysis, compliance, and risk scoring"
    layer = 3
    tags = ["domain", "container", "supply_chain"]
    requires = ["supply_chain_v2"]

    default_config = {
        "confidence_threshold": 0.85,
    }

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste supply_chain document text or chain from PDF/OCR...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "freight_cost_per_kg", "type": "number", "label": "Freight $/kg"},
                {"name": "landed_cost", "type": "number", "label": "Landed Cost"},
                {"name": "lead_time", "type": "number", "label": "Lead Time (days)"},
                {"name": "on_time_delivery_rate", "type": "number", "label": "On-Time Delivery %"},
                {"name": "delay_risk", "type": "number", "label": "Delay Risk"},
                {"name": "compliance_risk", "type": "number", "label": "Compliance Risk"},
                {"name": "cost_risk", "type": "number", "label": "Cost Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze Bill of Lading", "prompt": "Analyze this bill of lading"},
            {"icon": "🛃", "label": "Check Customs Compliance", "prompt": "Check this document for customs compliance"},
            {"icon": "⚠️", "label": "Score Supply Chain Risks", "prompt": "Score supply chain risks for this document"},
            {"icon": "🔍", "label": "Extract HS Codes & Incoterms", "prompt": "Extract HS codes and Incoterms from this document"},
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
        """Run full SupplyChainBlockV2 analysis."""
        block = self._resolve_block("supply_chain_v2")
        if block is None:
            return {"status": "error", "error": "%s_v2 block unavailable" % self.name}
        return await block.process(input_data, params)

    async def _extract_entities(self, input_data: Any, params: Dict) -> Dict:
        """Extract supply_chain entities only."""
        result = await self._analyze(input_data, params)
        if result.get("status") == "error":
            return result
        return {
            "status": "success",
            "entities": result.get("entities", {}),
            "confidence": result.get("confidence", 0),
        }

    async def _calculate_metrics(self, input_data: Any, params: Dict) -> Dict:
        """Calculate supply_chain metrics only."""
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
        """Score supply_chain risks only."""
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
