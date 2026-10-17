"""SupplyChain Block v2 - TypedBlock implementation

This is the v2 implementation that:
- Extends TypedBlock instead of UniversalContainer
- Accepts TextContent input (from pdf_v2, ocr_v2, etc.)
- Outputs SupplyChainAnalysis type
- Has a single process() entry point instead of action routing
- Internal methods are private (_ prefixed)
- Uses deterministic regex + math, no LLM calls, no external APIs
"""

import re
from typing import Any, Dict, List, Optional

from app.core.domain_block_v2 import DomainBlockV2
from app.core.schema_registry import TextContent, SupplyChainAnalysis
from app.core.supply_chain_types import RiskScore

from app.core.supply_chain_knowledge import SupplyChainKnowledge, COMPLIANCE_KEYWORDS
from app.core.http_errors import error_kind

_rk = SupplyChainKnowledge()


class SupplyChainBlockV2(DomainBlockV2):
    """
    SupplyChain Block v2 - TypedBlock implementation for supply_chain document analysis.

    Input: TextContent (extracted document text)
    Output: SupplyChainAnalysis (entities, metrics, compliance flags, risk scores)
    """

    name = "supply_chain_v2"
    version = "2.0"
    description = "SupplyChain document analysis with typed input/output"
    layer = 3
    tags = ["domain", "supply_chain", "v2"]
    requires = []

    default_config = {
        "confidence_threshold": 0.85,
    }

    input_schema = TextContent
    output_schema = SupplyChainAnalysis

    accepted_input_types = ["TextContent", "PDFContent"]
    produced_output_types = ["SupplyChainAnalysis"]

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste logistics document text...",
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

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Main entry point - analyze supply_chain document text."""
        params = params or {}

        text = self._extract_text(input_data)
        if not text:
            return self._empty_analysis("No text provided")

        custom_rules = params.get("custom_rules") or params.get("rules")
        if custom_rules:
            _rk.set_custom_rules(custom_rules)

        document_type = params.get("document_type") or params.get("analysis_type") or self._detect_document_type(text)

        if document_type == "bill_of_lading":
            return await self._analyze_bill_of_lading(text, params)
        if document_type == "customs_declaration":
            return await self._analyze_customs_declaration(text, params)
        if document_type == "certificate_of_origin":
            return await self._analyze_certificate_of_origin(text, params)
        if document_type == "waybill":
            return await self._analyze_waybill(text, params)
        if document_type == "packing_list":
            return await self._analyze_packing_list(text, params)
        if document_type == "delivery_order":
            return await self._analyze_delivery_order(text, params)
        if document_type == "inspection_certificate":
            return await self._analyze_inspection_certificate(text, params)
        if document_type == "dangerous_goods_declaration":
            return await self._analyze_dangerous_goods_declaration(text, params)

        return await self._analyze_generic(text, params)

    # ------------------------------------------------------------------
    # TEXT EXTRACTION
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DOCUMENT TYPE DETECTION
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        """Auto-detect supply_chain document type from content."""
        text_lower = text[:5000].lower()

        if any(kw in text_lower for kw in ['bol', 'bill of lading', 'shipper', 'consignee', 'vessel', 'port of loading', 'port of discharge']):
            return "bill_of_lading"
        if any(kw in text_lower for kw in ['customs', 'cbp', 'entry', 'hts', 'harmonized tariff', 'duty', 'import', 'export']):
            return "customs_declaration"
        if any(kw in text_lower for kw in ['coo', 'certificate of origin', 'country of origin', 'fta', 'preferential tariff']):
            return "certificate_of_origin"
        if any(kw in text_lower for kw in ['air waybill', 'awb', 'house bill', 'master bill', 'freight forwarder', 'iata']):
            return "waybill"
        if any(kw in text_lower for kw in ['packing list', 'carton', 'pallet', 'net weight', 'gross weight', 'dimensions', 'hs code']):
            return "packing_list"
        if any(kw in text_lower for kw in ['delivery order', 'do', 'release', 'cargo', 'container', 'seal number']):
            return "delivery_order"
        if any(kw in text_lower for kw in ['inspection', 'sgs', 'bv', 'intertek', 'quality', 'pre-shipment', 'psi']):
            return "inspection_certificate"
        if any(kw in text_lower for kw in ['imdg', 'adr', 'dangerous goods', 'msds', 'un number', 'class', 'proper shipping name']):
            return "dangerous_goods_declaration"

        return "generic"

    # ------------------------------------------------------------------
    # ANALYSIS METHODS (private)
    # ------------------------------------------------------------------

    async def _analyze_bill_of_lading(self, text: str, params: Dict) -> Dict:
        """Analyze bill of lading text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "bill_of_lading"
        return self._finalize_result(result, params)

    async def _analyze_customs_declaration(self, text: str, params: Dict) -> Dict:
        """Analyze customs declaration text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "customs_declaration"
        return self._finalize_result(result, params)

    async def _analyze_certificate_of_origin(self, text: str, params: Dict) -> Dict:
        """Analyze certificate of origin text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "certificate_of_origin"
        return self._finalize_result(result, params)

    async def _analyze_waybill(self, text: str, params: Dict) -> Dict:
        """Analyze waybill text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "waybill"
        return self._finalize_result(result, params)

    async def _analyze_packing_list(self, text: str, params: Dict) -> Dict:
        """Analyze packing list text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "packing_list"
        return self._finalize_result(result, params)

    async def _analyze_delivery_order(self, text: str, params: Dict) -> Dict:
        """Analyze delivery order text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "delivery_order"
        return self._finalize_result(result, params)

    async def _analyze_inspection_certificate(self, text: str, params: Dict) -> Dict:
        """Analyze inspection certificate text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "inspection_certificate"
        return self._finalize_result(result, params)

    async def _analyze_dangerous_goods_declaration(self, text: str, params: Dict) -> Dict:
        """Analyze dangerous goods declaration text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "dangerous_goods_declaration"
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
            "container_numbers": self._extract_container_numbers(text),
            "seal_numbers": self._extract_seal_numbers(text),
            "hs_codes": self._extract_hs_codes(text),
            "incoterms": self._extract_incoterms(text),
            "ports": self._extract_ports(text),
            "vessel_names": self._extract_vessel_names(text),
            "forwarders": self._extract_forwarders(text),
            "customs_brokers": self._extract_customs_brokers(text),
        }
        metrics = {
            "freight_cost_per_kg": self._extract_freight_cost_per_kg(**params.get("freight_cost_per_kg", {})),
            "cubic_meter_rate": self._extract_cubic_meter_rate(**params.get("cubic_meter_rate", {})),
            "duty_amount": self._extract_duty_amount(**params.get("duty_amount", {})),
            "landed_cost": self._extract_landed_cost(**params.get("landed_cost", {})),
            "lead_time": self._extract_lead_time(**params.get("lead_time", {})),
            "on_time_delivery_rate": self._extract_on_time_delivery_rate(**params.get("on_time_delivery_rate", {})),
            "order_accuracy_rate": self._extract_order_accuracy_rate(**params.get("order_accuracy_rate", {})),
            "inventory_days": self._extract_inventory_days(**params.get("inventory_days", {})),
        }
        compliance_flags = {
            "incoterms": self._check_incoterms(text),
            "customs": self._check_customs(text),
            "sanctions": self._check_sanctions(text),
            "dangerous_goods": self._check_dangerous_goods(text),
            "trade_agreement": self._check_trade_agreement(text),
        }
        risk_scores = {
            "delay_risk": self._score_delay_risk(text),
            "compliance_risk": self._score_compliance_risk(text),
            "cost_risk": self._score_cost_risk(text),
            "security_risk": self._score_security_risk(text),
            "supplier_risk": self._score_supplier_risk(text),
            "overall_risk": self._compute_overall_risk(text),
        }
        custom_rule_hits = _rk.check_custom_rules(text)

        return {
            "document_type": "unknown",
            "entities": entities,
            "metrics": metrics,
            "financials": {},
            "compliance_flags": compliance_flags,
            "risk_scores": risk_scores,
            "custom_rule_hits": custom_rule_hits,
            "text": text,
            "raw_text": text[:2000] if params.get("include_raw") else "",
            "metadata": {
                "extracted_at": self._timestamp(),
                "entity_count": sum(len(v) for v in entities.values()),
                "metric_count": sum(1 for v in metrics.values() if v and v.get("value") not in (None, [], "")),
                "shipment_id": self._extract_shipment_id(text),
            },
        }

    def _extract_shipment_id(self, text: str) -> Optional[str]:
        """Best-effort extraction of shipment id."""
        pattern = r"(?:shipment id|shipment_id)[:\s]+([A-Z][A-Za-z0-9\s&.,-]{2,60})"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            return match.group(1).strip()
        return None

    # ------------------------------------------------------------------
    # ENTITY EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_container_numbers(self, text: str) -> List[Dict]:
        """Extract container numbers from text."""
        found = []
        for match in re.finditer(r"\b([A-Z]{4}\d{7})\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "container_numbers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_seal_numbers(self, text: str) -> List[Dict]:
        """Extract seal numbers from text."""
        found = []
        for match in re.finditer(r"(?:seal|bolt seal|cable seal)\s*#?\s*(\d{6,12})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "seal_numbers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_hs_codes(self, text: str) -> List[Dict]:
        """Extract hs codes from text."""
        found = []
        for match in re.finditer(r"\b(\d{4}\.\d{2}\.\d{2}|\d{6}|\d{8}|\d{10})\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "hs_codes",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_incoterms(self, text: str) -> List[Dict]:
        """Extract incoterms from text."""
        found = []
        for match in re.finditer(r"\b(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "incoterms",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_ports(self, text: str) -> List[Dict]:
        """Extract ports from text."""
        found = []
        for match in re.finditer(r"(?:port of(?: loading| discharge)?|pol|pod|airport|seaport|icd)\s*[\-:]?\s*([A-Z][A-Za-z\s\-]{2,40})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "ports",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_vessel_names(self, text: str) -> List[Dict]:
        """Extract vessel names from text."""
        found = []
        for match in re.finditer(r"(?:mv|ss|vessel|ship|carrier|airline|flight number)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s\-]{2,40})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "vessel_names",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_forwarders(self, text: str) -> List[Dict]:
        """Extract forwarders from text."""
        found = []
        for match in re.finditer(r"(?:freight forwarder|nvocc|logistics provider|3pl|4pl)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "forwarders",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_customs_brokers(self, text: str) -> List[Dict]:
        """Extract customs brokers from text."""
        found = []
        for match in re.finditer(r"(?:customs broker|customs agent|cha|broker reference)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "customs_brokers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    # ------------------------------------------------------------------
    # METRICS & FORMULA EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_freight_cost_per_kg(self, total_freight=None, total_weight_kg=None) -> Dict[str, Any]:
        """Calculate freight cost per kg."""
        try:
            value = self._safe_divide(total_freight, total_weight_kg) if (total_freight is not None and total_weight_kg is not None) else None
            if value is None:
                return {"name": "freight_cost_per_kg", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "freight_cost_per_kg", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "freight_cost_per_kg", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_cubic_meter_rate(self, total_freight=None, total_cbm=None) -> Dict[str, Any]:
        """Calculate cubic meter rate."""
        try:
            value = self._safe_divide(total_freight, total_cbm) if (total_freight is not None and total_cbm is not None) else None
            if value is None:
                return {"name": "cubic_meter_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "cubic_meter_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "cubic_meter_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_duty_amount(self, dutiable_value=None, duty_rate=None) -> Dict[str, Any]:
        """Calculate duty amount."""
        try:
            value = (dutiable_value * duty_rate) if dutiable_value is not None and duty_rate is not None else None
            if value is None:
                return {"name": "duty_amount", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "duty_amount", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "duty_amount", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_landed_cost(self, unit_cost=None, freight=None, insurance=None, duty=None, handling=None) -> Dict[str, Any]:
        """Calculate landed cost."""
        try:
            value = (unit_cost + freight + insurance + duty + handling) if unit_cost is not None else None
            if value is None:
                return {"name": "landed_cost", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "landed_cost", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "landed_cost", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_lead_time(self, order_date=None, delivery_date=None) -> Dict[str, Any]:
        """Calculate lead time."""
        try:
            value = self._days_between(order_date, delivery_date) if (order_date is not None and delivery_date is not None) else None
            if value is None:
                return {"name": "lead_time", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "lead_time", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "lead_time", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_on_time_delivery_rate(self, on_time_deliveries=None, total_deliveries=None) -> Dict[str, Any]:
        """Calculate on time delivery rate."""
        try:
            value = self._safe_divide(on_time_deliveries, total_deliveries, scale=100) if (on_time_deliveries is not None and total_deliveries is not None) else None
            if value is None:
                return {"name": "on_time_delivery_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "on_time_delivery_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "on_time_delivery_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_order_accuracy_rate(self, accurate_orders=None, total_orders=None) -> Dict[str, Any]:
        """Calculate order accuracy rate."""
        try:
            value = self._safe_divide(accurate_orders, total_orders, scale=100) if (accurate_orders is not None and total_orders is not None) else None
            if value is None:
                return {"name": "order_accuracy_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "order_accuracy_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "order_accuracy_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_inventory_days(self, inventory=None, daily_usage=None) -> Dict[str, Any]:
        """Calculate inventory days."""
        try:
            value = self._safe_divide(inventory, daily_usage) if (inventory is not None and daily_usage is not None) else None
            if value is None:
                return {"name": "inventory_days", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "inventory_days", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "inventory_days", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    # ------------------------------------------------------------------
    # REGULATORY & COMPLIANCE CHECKING (private)
    # ------------------------------------------------------------------

    def _check_incoterms(self, text: str) -> Dict[str, Any]:
        """Check incoterms compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["incoterms"] if kw in text.lower()]
        return {
            "regulation": "incoterms",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_customs(self, text: str) -> Dict[str, Any]:
        """Check customs compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["customs"] if kw in text.lower()]
        return {
            "regulation": "customs",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_sanctions(self, text: str) -> Dict[str, Any]:
        """Check sanctions compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["sanctions"] if kw in text.lower()]
        return {
            "regulation": "sanctions",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_dangerous_goods(self, text: str) -> Dict[str, Any]:
        """Check dangerous goods compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["dangerous_goods"] if kw in text.lower()]
        return {
            "regulation": "dangerous_goods",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_trade_agreement(self, text: str) -> Dict[str, Any]:
        """Check trade agreement compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["trade_agreement"] if kw in text.lower()]
        return {
            "regulation": "trade_agreement",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    # ------------------------------------------------------------------
    # RISK SCORING (private)
    # ------------------------------------------------------------------

    def _score_delay_risk(self, text: str) -> RiskScore:
        """Score delay risk."""
        data = _rk.check_risk_keywords(text).get("delay_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="delay_risk",
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

    def _score_cost_risk(self, text: str) -> RiskScore:
        """Score cost risk."""
        data = _rk.check_risk_keywords(text).get("cost_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="cost_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_security_risk(self, text: str) -> RiskScore:
        """Score security risk."""
        data = _rk.check_risk_keywords(text).get("security_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="security_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

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
