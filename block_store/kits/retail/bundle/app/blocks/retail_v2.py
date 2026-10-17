"""Retail Block v2 - TypedBlock implementation

This is the v2 implementation that:
- Extends TypedBlock instead of UniversalContainer
- Accepts TextContent input (from pdf_v2, ocr_v2, etc.)
- Outputs RetailAnalysis type
- Has a single process() entry point instead of action routing
- Internal methods are private (_ prefixed)
- Uses deterministic regex + math, no LLM calls, no external APIs
"""

import re
from typing import Any, Dict, List, Optional

from app.core.domain_block_v2 import DomainBlockV2
from app.core.schema_registry import TextContent, RetailAnalysis
from app.core.retail_types import RiskScore

from app.core.retail_knowledge import RetailKnowledge, COMPLIANCE_KEYWORDS
from app.core.http_errors import error_kind

_rk = RetailKnowledge()


class RetailBlockV2(DomainBlockV2):
    """
    Retail Block v2 - TypedBlock implementation for retail document analysis.

    Input: TextContent (extracted document text)
    Output: RetailAnalysis (entities, metrics, compliance flags, risk scores)
    """

    name = "retail_v2"
    version = "2.0"
    description = "Retail document analysis with typed input/output"
    layer = 3
    tags = ["domain", "retail", "v2"]
    requires = []

    default_config = {
        "confidence_threshold": 0.85,
    }

    input_schema = TextContent
    output_schema = RetailAnalysis

    accepted_input_types = ["TextContent", "PDFContent"]
    produced_output_types = ["RetailAnalysis"]

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste retail document text...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "gross_margin", "type": "number", "label": "Gross Margin %"},
                {"name": "inventory_turnover", "type": "number", "label": "Inventory Turnover"},
                {"name": "sell_through_rate", "type": "number", "label": "Sell-Through Rate %"},
                {"name": "aov", "type": "number", "label": "Average Order Value"},
                {"name": "supplier_risk", "type": "number", "label": "Supplier Risk"},
                {"name": "fraud_risk", "type": "number", "label": "Fraud Risk"},
                {"name": "compliance_risk", "type": "number", "label": "Compliance Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze Purchase Order", "prompt": "Analyze this purchase order"},
            {"icon": "📦", "label": "Check Inventory Report", "prompt": "Check this inventory report"},
            {"icon": "⚠️", "label": "Score Retail Risks", "prompt": "Score retail risks for this document"},
            {"icon": "🔍", "label": "Extract SKUs & Pricing", "prompt": "Extract SKUs and pricing from this document"},
        ],
    }

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Main entry point - analyze retail document text."""
        params = params or {}

        text = self._extract_text(input_data)
        if not text:
            return self._empty_analysis("No text provided")

        custom_rules = params.get("custom_rules") or params.get("rules")
        if custom_rules:
            _rk.set_custom_rules(custom_rules)

        document_type = params.get("document_type") or params.get("analysis_type") or self._detect_document_type(text)

        if document_type == "purchase_order":
            return await self._analyze_purchase_order(text, params)
        if document_type == "invoice":
            return await self._analyze_invoice(text, params)
        if document_type == "supplier_contract":
            return await self._analyze_supplier_contract(text, params)
        if document_type == "return_authorization":
            return await self._analyze_return_authorization(text, params)
        if document_type == "inventory_report":
            return await self._analyze_inventory_report(text, params)
        if document_type == "pricing_sheet":
            return await self._analyze_pricing_sheet(text, params)
        if document_type == "shipping_manifest":
            return await self._analyze_shipping_manifest(text, params)
        if document_type == "customer_complaint":
            return await self._analyze_customer_complaint(text, params)

        return await self._analyze_generic(text, params)

    # ------------------------------------------------------------------
    # TEXT EXTRACTION
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DOCUMENT TYPE DETECTION
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        """Auto-detect retail document type from content."""
        text_lower = text[:5000].lower()

        if any(kw in text_lower for kw in ['po', 'purchase order', 'buyer', 'seller', 'quantity', 'unit price', 'delivery date']):
            return "purchase_order"
        if any(kw in text_lower for kw in ['invoice', 'bill to', 'payment due', 'line items', 'subtotal', 'tax', 'total']):
            return "invoice"
        if any(kw in text_lower for kw in ['supplier agreement', 'vendor', 'moq', 'lead time', 'exclusivity', 'termination']):
            return "supplier_contract"
        if any(kw in text_lower for kw in ['rma', 'return', 'refund', 'exchange', 'defective', 'credit memo']):
            return "return_authorization"
        if any(kw in text_lower for kw in ['stock', 'sku', 'on hand', 'reorder point', 'safety stock', 'dead stock', 'shrinkage']):
            return "inventory_report"
        if any(kw in text_lower for kw in ['msrp', 'map', 'wholesale', 'retail margin', 'discount tier', 'promotional price']):
            return "pricing_sheet"
        if any(kw in text_lower for kw in ['manifest', 'carrier', 'tracking', 'weight', 'dimensions', 'freight class', 'bol']):
            return "shipping_manifest"
        if any(kw in text_lower for kw in ['complaint', 'defective', 'damaged', 'wrong item', 'refund request', 'chargeback']):
            return "customer_complaint"

        return "generic"

    # ------------------------------------------------------------------
    # ANALYSIS METHODS (private)
    # ------------------------------------------------------------------

    async def _analyze_purchase_order(self, text: str, params: Dict) -> Dict:
        """Analyze purchase order text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "purchase_order"
        return self._finalize_result(result, params)

    async def _analyze_invoice(self, text: str, params: Dict) -> Dict:
        """Analyze invoice text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "invoice"
        return self._finalize_result(result, params)

    async def _analyze_supplier_contract(self, text: str, params: Dict) -> Dict:
        """Analyze supplier contract text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "supplier_contract"
        return self._finalize_result(result, params)

    async def _analyze_return_authorization(self, text: str, params: Dict) -> Dict:
        """Analyze return authorization text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "return_authorization"
        return self._finalize_result(result, params)

    async def _analyze_inventory_report(self, text: str, params: Dict) -> Dict:
        """Analyze inventory report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "inventory_report"
        return self._finalize_result(result, params)

    async def _analyze_pricing_sheet(self, text: str, params: Dict) -> Dict:
        """Analyze pricing sheet text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "pricing_sheet"
        return self._finalize_result(result, params)

    async def _analyze_shipping_manifest(self, text: str, params: Dict) -> Dict:
        """Analyze shipping manifest text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "shipping_manifest"
        return self._finalize_result(result, params)

    async def _analyze_customer_complaint(self, text: str, params: Dict) -> Dict:
        """Analyze customer complaint text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "customer_complaint"
        return self._finalize_result(result, params)

    async def _analyze_generic(self, text: str, params: Dict) -> Dict:
        """Generic analysis for unknown document types."""
        result = self._build_analysis(text, params)
        result["document_type"] = "generic"
        return self._finalize_result(result, params)

    # ------------------------------------------------------------------
    # BUILDERS
    # ------------------------------------------------------------------

    def _build_analysis(self, text: str, params: Dict) -> Dict:
        """Run all extraction passes and return a working dict."""
        entities = {
            "skus": self._extract_skus(text),
            "product_names": self._extract_product_names(text),
            "quantities": self._extract_quantities(text),
            "prices": self._extract_prices(text),
            "suppliers": self._extract_suppliers(text),
            "customers": self._extract_customers(text),
            "order_numbers": self._extract_order_numbers(text),
            "tracking_numbers": self._extract_tracking_numbers(text),
        }
        metrics = {
            "gross_margin": self._extract_gross_margin(**params.get("gross_margin", {})),
            "inventory_turnover": self._extract_inventory_turnover(**params.get("inventory_turnover", {})),
            "sell_through_rate": self._extract_sell_through_rate(**params.get("sell_through_rate", {})),
            "shrinkage": self._extract_shrinkage(**params.get("shrinkage", {})),
            "return_rate": self._extract_return_rate(**params.get("return_rate", {})),
            "conversion_rate": self._extract_conversion_rate(**params.get("conversion_rate", {})),
            "aov": self._extract_aov(**params.get("aov", {})),
            "cart_abandonment": self._extract_cart_abandonment(**params.get("cart_abandonment", {})),
        }
        financials = {
            "total_revenue": self._extract_money_value(text, "total_revenue"),
            "cogs": self._extract_money_value(text, "cogs"),
            "gross_profit": self._extract_money_value(text, "gross_profit"),
            "taxes": self._extract_money_value(text, "taxes"),
            "total": self._extract_money_value(text, "total"),
        }
        compliance_flags = {
            "consumer_protection": self._check_consumer_protection(text),
            "product_safety": self._check_product_safety(text),
            "gdpr": self._check_gdpr(text),
            "payment_compliance": self._check_payment_compliance(text),
            "import_export": self._check_import_export(text),
        }
        risk_scores = {
            "supplier_risk": self._score_supplier_risk(text),
            "inventory_risk": self._score_inventory_risk(text),
            "fraud_risk": self._score_fraud_risk(text),
            "compliance_risk": self._score_compliance_risk(text),
            "reputation_risk": self._score_reputation_risk(text),
            "overall_risk": self._compute_overall_risk(text),
        }
        custom_rule_hits = _rk.check_custom_rules(text)

        return {
            "document_type": "unknown",
            "entities": entities,
            "metrics": metrics,
            "financials": financials,
            "compliance_flags": compliance_flags,
            "risk_scores": risk_scores,
            "custom_rule_hits": custom_rule_hits,
            "text": text,
            "raw_text": text[:2000] if params.get("include_raw") else "",
            "metadata": {
                "extracted_at": self._timestamp(),
                "entity_count": sum(len(v) for v in entities.values()),
                "metric_count": sum(1 for v in metrics.values() if v and v.get("value") not in (None, [], "")),
                "store_name": self._extract_store_name(text),
            },
        }

    def _extract_store_name(self, text: str) -> Optional[str]:
        """Best-effort extraction of store name."""
        pattern = r"(?:store name|store_name)[:\s]+([A-Z][A-Za-z0-9\s&.,-]{2,60})"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            return match.group(1).strip()
        return None

    # ------------------------------------------------------------------
    # ENTITY EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_skus(self, text: str) -> List[Dict]:
        """Extract skus from text."""
        found = []
        for match in re.finditer(r"SKU\s*[\-:]?\s*([A-Z0-9\-]{6,20})|(?:sku|product code|item code)\s*[\-:]?\s*([A-Z0-9\-]{6,20})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "skus",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_product_names(self, text: str) -> List[Dict]:
        """Extract product names from text."""
        found = []
        for match in re.finditer(r"(?:product name|item description|model|brand)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s\-&]{2,60})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "product_names",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_quantities(self, text: str) -> List[Dict]:
        """Extract quantities from text."""
        found = []
        for match in re.finditer(r"(\d+)\s*(ea|units|pcs|boxes|cases|pallets)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "quantities",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_prices(self, text: str) -> List[Dict]:
        """Extract prices from text."""
        found = []
        for match in re.finditer(r"(?:\$|USD|EUR|GBP)\s*([\d,]+(?:\.\d{1,2})?)\s*(?:per unit|unit price|each|ea)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "prices",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_suppliers(self, text: str) -> List[Dict]:
        """Extract suppliers from text."""
        found = []
        for match in re.finditer(r"(?:supplier|vendor|manufacturer|sold by|shipped by)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?|Limited|GmbH)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "suppliers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_customers(self, text: str) -> List[Dict]:
        """Extract customers from text."""
        found = []
        for match in re.finditer(r"(?:customer|buyer|bill to|ship to|account number)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?|Limited)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "customers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_order_numbers(self, text: str) -> List[Dict]:
        """Extract order numbers from text."""
        found = []
        for match in re.finditer(r"(?:order|po|invoice)\s*#?\s*(\d{6,12})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "order_numbers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_tracking_numbers(self, text: str) -> List[Dict]:
        """Extract tracking numbers from text."""
        found = []
        for match in re.finditer(r"\b(1Z[A-Z0-9]{16}|\d{4}[\s\-]?\d{4}[\s\-]?\d{4}|\d{12,20})\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "tracking_numbers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    # ------------------------------------------------------------------
    # METRICS & FORMULA EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_gross_margin(self, selling_price=None, cost_price=None) -> Dict[str, Any]:
        """Calculate gross margin."""
        try:
            value = self._safe_divide(selling_price - cost_price, selling_price, scale=100) if (selling_price is not None and cost_price is not None) else None
            if value is None:
                return {"name": "gross_margin", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "gross_margin", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "gross_margin", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_inventory_turnover(self, cogs=None, average_inventory=None) -> Dict[str, Any]:
        """Calculate inventory turnover."""
        try:
            value = self._safe_divide(cogs, average_inventory) if (cogs is not None and average_inventory is not None) else None
            if value is None:
                return {"name": "inventory_turnover", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "inventory_turnover", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "inventory_turnover", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_sell_through_rate(self, units_sold=None, units_received=None) -> Dict[str, Any]:
        """Calculate sell through rate."""
        try:
            value = self._safe_divide(units_sold, units_received, scale=100) if (units_sold is not None and units_received is not None) else None
            if value is None:
                return {"name": "sell_through_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "sell_through_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "sell_through_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_shrinkage(self, recorded_inventory=None, actual_inventory=None) -> Dict[str, Any]:
        """Calculate shrinkage."""
        try:
            value = self._safe_divide(recorded_inventory - actual_inventory, recorded_inventory, scale=100) if (recorded_inventory is not None and actual_inventory is not None) else None
            if value is None:
                return {"name": "shrinkage", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "shrinkage", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "shrinkage", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_return_rate(self, returns=None, total_sales=None) -> Dict[str, Any]:
        """Calculate return rate."""
        try:
            value = self._safe_divide(returns, total_sales, scale=100) if (returns is not None and total_sales is not None) else None
            if value is None:
                return {"name": "return_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "return_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "return_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_conversion_rate(self, orders=None, visitors=None) -> Dict[str, Any]:
        """Calculate conversion rate."""
        try:
            value = self._safe_divide(orders, visitors, scale=100) if (orders is not None and visitors is not None) else None
            if value is None:
                return {"name": "conversion_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "conversion_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "conversion_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_aov(self, total_revenue=None, orders=None) -> Dict[str, Any]:
        """Calculate aov."""
        try:
            value = self._safe_divide(total_revenue, orders) if (total_revenue is not None and orders is not None) else None
            if value is None:
                return {"name": "aov", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "aov", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "aov", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_cart_abandonment(self, carts_created=None, orders_completed=None) -> Dict[str, Any]:
        """Calculate cart abandonment."""
        try:
            value = self._safe_divide(carts_created - orders_completed, carts_created, scale=100) if (carts_created is not None and orders_completed is not None) else None
            if value is None:
                return {"name": "cart_abandonment", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "cart_abandonment", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "cart_abandonment", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_money_value(self, text: str, label: str) -> Dict[str, Any]:
        """Best-effort extraction of a monetary value by label."""
        pattern = r"(?:" + label.replace("_", " ") + r"|" + label + r")[:\s]+[\$€£¥]?\s*([\d,]+(?:\.\d{1,2})?)\s*(million|billion|thousand|m|bn|b|k)?"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            amount = float(match.group(1).replace(",", ""))
            mult = match.group(2)
            if mult:
                ml = mult.lower()
                if ml in {"million", "m"}:
                    amount *= 1_000_000
                elif ml in {"billion", "bn", "b"}:
                    amount *= 1_000_000_000
                elif ml in {"thousand", "k"}:
                    amount *= 1_000
            return {"name": label, "value": amount, "confidence": 0.8}
        return {"name": label, "value": None, "error": "Not found"}

    # ------------------------------------------------------------------
    # REGULATORY & COMPLIANCE CHECKING (private)
    # ------------------------------------------------------------------

    def _check_consumer_protection(self, text: str) -> Dict[str, Any]:
        """Check consumer protection compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["consumer_protection"] if kw in text.lower()]
        return {
            "regulation": "consumer_protection",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_product_safety(self, text: str) -> Dict[str, Any]:
        """Check product safety compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["product_safety"] if kw in text.lower()]
        return {
            "regulation": "product_safety",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_gdpr(self, text: str) -> Dict[str, Any]:
        """Check gdpr compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["gdpr"] if kw in text.lower()]
        return {
            "regulation": "gdpr",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_payment_compliance(self, text: str) -> Dict[str, Any]:
        """Check payment compliance compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["payment_compliance"] if kw in text.lower()]
        return {
            "regulation": "payment_compliance",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_import_export(self, text: str) -> Dict[str, Any]:
        """Check import export compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["import_export"] if kw in text.lower()]
        return {
            "regulation": "import_export",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    # ------------------------------------------------------------------
    # RISK SCORING (private)
    # ------------------------------------------------------------------

    def _score_supplier_risk(self, text: str) -> RiskScore:
        """Score supplier risk."""
        data = _rk.check_risk_keywords(text).get("supplier_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="supplier_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_inventory_risk(self, text: str) -> RiskScore:
        """Score inventory risk."""
        data = _rk.check_risk_keywords(text).get("inventory_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="inventory_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_fraud_risk(self, text: str) -> RiskScore:
        """Score fraud risk."""
        data = _rk.check_risk_keywords(text).get("fraud_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="fraud_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_compliance_risk(self, text: str) -> RiskScore:
        """Score compliance risk."""
        data = _rk.check_risk_keywords(text).get("compliance_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="compliance_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_reputation_risk(self, text: str) -> RiskScore:
        """Score reputation risk."""
        data = _rk.check_risk_keywords(text).get("reputation_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="reputation_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    def _compute_overall_risk(self, text: str) -> RiskScore:
        """Compute overall risk from individual risk scores."""
        risks = _rk.check_risk_keywords(text)
        total = sum(r.get("score", 0.0) for r in risks.values())
        count = len(risks) or 1
        score = total / count
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="overall_risk",
            score=round(score, 2),
            level=level,
            indicators=[],
            confidence=round(min(1.0, score + 0.1), 2),
        )
