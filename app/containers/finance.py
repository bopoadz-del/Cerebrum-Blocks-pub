"""Finance Container - Financial domain container v1.0.

Wraps FinanceBlockV2 and routes domain actions. Accepts user custom rules
injection through params["custom_rules"].
"""

import logging
from typing import Any, Callable, Dict

from app.containers.base import DomainContainer

logger = logging.getLogger(__name__)


class FinanceContainer(DomainContainer):
    """
    Finance Container: Financial document analysis, entity extraction,
    formula calculation, regulatory compliance checks, and risk scoring.
    """

    name = "finance"
    version = "1.0"
    description = "Financial document analysis, entity extraction, formulas, compliance, and risk scoring"
    layer = 3
    tags = ["domain", "container", "finance"]
    requires = ["finance_v2"]

    default_config = {
        "confidence_threshold": 0.85,
    }

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste financial document text or chain from PDF/OCR...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "revenue", "type": "number", "label": "Revenue"},
                {"name": "net_income", "type": "number", "label": "Net Income"},
                {"name": "total_assets", "type": "number", "label": "Total Assets"},
                {"name": "total_liabilities", "type": "number", "label": "Total Liabilities"},
                {"name": "equity", "type": "number", "label": "Equity"},
                {"name": "credit_risk_score", "type": "number", "label": "Credit Risk"},
                {"name": "market_risk_score", "type": "number", "label": "Market Risk"},
                {"name": "operational_risk_score", "type": "number", "label": "Operational Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📊", "label": "Analyze Balance Sheet", "prompt": "Analyze this balance sheet document"},
            {"icon": "⚖️", "label": "Check Regulatory Compliance", "prompt": "Check this document for regulatory compliance flags"},
            {"icon": "📈", "label": "Calculate Risk Scores", "prompt": "Calculate risk scores for this financial document"},
            {"icon": "🔍", "label": "Extract Entities", "prompt": "Extract ISINs, tickers, currency pairs and counterparties from this document"},
        ],
    }

    def get_actions(self) -> Dict[str, Callable]:
        """Return action name → handler mapping."""
        return {
            "analyze": self._analyze,
            "extract_entities": self._extract_entities,
            "calculate_formulas": self._calculate_formulas,
            "check_compliance": self._check_compliance,
            "score_risk": self._score_risk,
            "health": self._health,
        }

    # ------------------------------------------------------------------
    # HANDLERS
    # ------------------------------------------------------------------

    async def _analyze(self, input_data: Any, params: Dict) -> Dict:
        """Run full FinanceBlockV2 analysis."""
        block = self._resolve_block("finance_v2")
        if block is None:
            return {"status": "error", "error": "finance_v2 block unavailable"}
        return await block.process(input_data, params)

    async def _extract_entities(self, input_data: Any, params: Dict) -> Dict:
        """Extract finance entities only."""
        merged = dict(params or {})
        merged["analysis_type"] = "generic"
        result = await self._analyze(input_data, merged)
        if result.get("status") == "error":
            return result
        return {
            "status": "success",
            "entities": result.get("entities", {}),
            "confidence": result.get("confidence", 0),
        }

    async def _calculate_formulas(self, input_data: Any, params: Dict) -> Dict:
        """Calculate finance formulas only."""
        result = await self._analyze(input_data, params)
        if result.get("status") == "error":
            return result
        return {
            "status": "success",
            "formulas": result.get("formulas", {}),
            "confidence": result.get("confidence", 0),
        }

    async def _check_compliance(self, input_data: Any, params: Dict) -> Dict:
        """Check regulatory compliance only."""
        result = await self._analyze(input_data, params)
        if result.get("status") == "error":
            return result
        return {
            "status": "success",
            "regulatory_flags": result.get("regulatory_flags", {}),
            "custom_rule_hits": result.get("custom_rule_hits", []),
            "confidence": result.get("confidence", 0),
        }

    async def _score_risk(self, input_data: Any, params: Dict) -> Dict:
        """Score financial risks only."""
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
