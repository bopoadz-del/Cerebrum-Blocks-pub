"""Shared base class for generated v2 domain extraction blocks.

This module provides ``DomainBlockV2`` which inherits from
``app.core.typed_block.TypedBlock`` and moves common infrastructure
shared by the generated v2 domain blocks into one place.
"""

from typing import Any, Dict, List
from datetime import datetime, timezone

from app.core.typed_block import TypedBlock
from app.core.schema_registry import TextContent
from app.core.confidence import assess_extraction_confidence


class DomainBlockV2(TypedBlock):
    """Base class for v2 domain document-analysis blocks.

    Subclasses still define their own ``output_schema``, ``name``,
    ``description``, ``tags``, ``requires``, ``default_config``,
    ``ui_schema``, and domain-specific ``process()`` method.
    """

    input_schema = TextContent
    accepted_input_types = ["TextContent", "PDFContent"]

    def _extract_text(self, input_data: Any) -> str:
        """Extract text from dict/string/PDFContent/TextContent."""
        if isinstance(input_data, str):
            return input_data
        if isinstance(input_data, dict):
            if "text" in input_data:
                return input_data["text"]
            return input_data.get("content", "")
        return ""

    def _empty_analysis(self, message: str) -> Dict[str, Any]:
        """Return a standard empty/error result dict."""
        return {
            "status": "error",
            "error": message,
            "document_type": "unknown",
            "entities": {},
            "metrics": {},
            "financials": {},
            "compliance_flags": {},
            "risk_scores": {},
            "confidence": 0.0,
            "metadata": {"extracted_at": self._timestamp()},
        }

    def _finalize_result(self, result: Dict, params: Dict) -> Dict:
        """Compute confidence, add threshold metadata, remove working text."""
        expected_fields = [
            key
            for key in (
                "entities",
                "metrics",
                "financials",
                "compliance_flags",
                "risk_scores",
                "formulas",
                "regulatory_flags",
            )
            if key in result
        ]
        conf_report = assess_extraction_confidence(
            result, expected_fields=expected_fields
        )
        result["confidence"] = conf_report["overall"]
        result["confidence_report"] = conf_report
        if "metadata" not in result:
            result["metadata"] = {}
        result["metadata"]["confidence_threshold"] = params.get(
            "confidence_threshold",
            self.default_config.get("confidence_threshold", 0.85),
        )
        if "text" in result:
            del result["text"]
        return result

    def _deduplicate_entities(self, items: List[Dict]) -> List[Dict]:
        """Deduplicate items by lowercase stripped value, return first 50."""
        seen = set()
        unique = []
        for item in items:
            key = str(item.get("value", "")).strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(item)
        return unique[:50]

    def _timestamp(self) -> str:
        """Return an ISO UTC timestamp."""
        return datetime.now(timezone.utc).isoformat()

    def _risk_level(self, score: float) -> str:
        """Map a 0-1 risk score to low/medium/high."""
        if score < 0.33:
            return "low"
        if score < 0.66:
            return "medium"
        return "high"
