"""Automotive Block v2 - TypedBlock implementation

This is the v2 implementation that:
- Extends TypedBlock instead of UniversalContainer
- Accepts TextContent input (from pdf_v2, ocr_v2, etc.)
- Outputs AutomotiveAnalysis type
- Has a single process() entry point instead of action routing
- Internal methods are private (_ prefixed)
- Uses deterministic regex + math, no LLM calls, no external APIs
"""

import re
from typing import Any, Dict, List, Optional

from app.core.domain_block_v2 import DomainBlockV2
from app.core.schema_registry import TextContent, AutomotiveAnalysis
from app.core.automotive_types import RiskScore

from app.core.automotive_knowledge import AutomotiveKnowledge, COMPLIANCE_KEYWORDS
from app.core.http_errors import error_kind

_rk = AutomotiveKnowledge()


class AutomotiveBlockV2(DomainBlockV2):
    """
    Automotive Block v2 - TypedBlock implementation for automotive document analysis.

    Input: TextContent (extracted document text)
    Output: AutomotiveAnalysis (entities, metrics, compliance flags, risk scores)
    """

    name = "automotive_v2"
    version = "2.0"
    description = "Automotive document analysis with typed input/output"
    layer = 3
    tags = ["domain", "automotive", "v2"]
    requires = []

    default_config = {
        "confidence_threshold": 0.85,
    }

    input_schema = TextContent
    output_schema = AutomotiveAnalysis

    accepted_input_types = ["TextContent", "PDFContent"]
    produced_output_types = ["AutomotiveAnalysis"]

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste automotive document text...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "total_cost_of_ownership", "type": "number", "label": "TCO"},
                {"name": "depreciation_rate", "type": "number", "label": "Depreciation %/yr"},
                {"name": "fuel_efficiency", "type": "number", "label": "Fuel Efficiency"},
                {"name": "defect_rate", "type": "number", "label": "Defect Rate PPM"},
                {"name": "safety_risk", "type": "number", "label": "Safety Risk"},
                {"name": "supply_chain_risk", "type": "number", "label": "Supply Chain Risk"},
                {"name": "compliance_risk", "type": "number", "label": "Compliance Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze Recall Notice", "prompt": "Analyze this recall notice"},
            {"icon": "🚗", "label": "Check NHTSA Compliance", "prompt": "Check this document for NHTSA compliance"},
            {"icon": "⚠️", "label": "Score Automotive Risks", "prompt": "Score automotive risks for this document"},
            {"icon": "🔍", "label": "Extract VINs & Parts", "prompt": "Extract VINs and parts from this document"},
        ],
    }

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Main entry point - analyze automotive document text."""
        params = params or {}

        text = self._extract_text(input_data)
        if not text:
            return self._empty_analysis("No text provided")

        custom_rules = params.get("custom_rules") or params.get("rules")
        if custom_rules:
            _rk.set_custom_rules(custom_rules)

        document_type = params.get("document_type") or params.get("analysis_type") or self._detect_document_type(text)

        if document_type == "recall_notice":
            return await self._analyze_recall_notice(text, params)
        if document_type == "service_report":
            return await self._analyze_service_report(text, params)
        if document_type == "warranty_claim":
            return await self._analyze_warranty_claim(text, params)
        if document_type == "supplier_quality_report":
            return await self._analyze_supplier_quality_report(text, params)
        if document_type == "build_sheet":
            return await self._analyze_build_sheet(text, params)
        if document_type == "vehicle_inspection":
            return await self._analyze_vehicle_inspection(text, params)
        if document_type == "fleet_management":
            return await self._analyze_fleet_management(text, params)
        if document_type == "regulatory_certification":
            return await self._analyze_regulatory_certification(text, params)

        return await self._analyze_generic(text, params)

    # ------------------------------------------------------------------
    # TEXT EXTRACTION
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DOCUMENT TYPE DETECTION
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        """Auto-detect automotive document type from content."""
        text_lower = text[:5000].lower()

        if any(kw in text_lower for kw in ['recall', 'nhtsa', 'safety defect', 'campaign', 'affected vehicles', 'remedy', 'dealer']):
            return "recall_notice"
        if any(kw in text_lower for kw in ['service', 'maintenance', 'repair', 'technician', 'labor', 'parts', 'mileage', 'vin']):
            return "service_report"
        if any(kw in text_lower for kw in ['warranty', 'claim', 'powertrain', 'bumper-to-bumper', 'extended', 'denial', 'goodwill']):
            return "warranty_claim"
        if any(kw in text_lower for kw in ['ppap', 'apqp', 'supplier', 'defect', 'ppm', 'corrective action', '8d']):
            return "supplier_quality_report"
        if any(kw in text_lower for kw in ['build sheet', 'monroney', 'msrp', 'options', 'trim', 'engine', 'transmission', 'color code']):
            return "build_sheet"
        if any(kw in text_lower for kw in ['inspection', 'safety', 'emissions', 'brake', 'tire', 'suspension', 'obd', 'check engine']):
            return "vehicle_inspection"
        if any(kw in text_lower for kw in ['fleet', 'utilization', 'total cost of ownership', 'tco', 'depreciation', 'fuel', 'telematics']):
            return "fleet_management"
        if any(kw in text_lower for kw in ['epa', 'carb', 'euro', 'wltp', 'homologation', 'type approval', 'fmvss', 'crash test']):
            return "regulatory_certification"

        return "generic"

    # ------------------------------------------------------------------
    # ANALYSIS METHODS (private)
    # ------------------------------------------------------------------

    async def _analyze_recall_notice(self, text: str, params: Dict) -> Dict:
        """Analyze recall notice text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "recall_notice"
        return self._finalize_result(result, params)

    async def _analyze_service_report(self, text: str, params: Dict) -> Dict:
        """Analyze service report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "service_report"
        return self._finalize_result(result, params)

    async def _analyze_warranty_claim(self, text: str, params: Dict) -> Dict:
        """Analyze warranty claim text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "warranty_claim"
        return self._finalize_result(result, params)

    async def _analyze_supplier_quality_report(self, text: str, params: Dict) -> Dict:
        """Analyze supplier quality report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "supplier_quality_report"
        return self._finalize_result(result, params)

    async def _analyze_build_sheet(self, text: str, params: Dict) -> Dict:
        """Analyze build sheet text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "build_sheet"
        return self._finalize_result(result, params)

    async def _analyze_vehicle_inspection(self, text: str, params: Dict) -> Dict:
        """Analyze vehicle inspection text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "vehicle_inspection"
        return self._finalize_result(result, params)

    async def _analyze_fleet_management(self, text: str, params: Dict) -> Dict:
        """Analyze fleet management text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "fleet_management"
        return self._finalize_result(result, params)

    async def _analyze_regulatory_certification(self, text: str, params: Dict) -> Dict:
        """Analyze regulatory certification text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "regulatory_certification"
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
            "vins": self._extract_vins(text),
            "makes": self._extract_makes(text),
            "models": self._extract_models(text),
            "model_years": self._extract_model_years(text),
            "mileage": self._extract_mileage(text),
            "parts_numbers": self._extract_parts_numbers(text),
            "dealers": self._extract_dealers(text),
            "suppliers": self._extract_suppliers(text),
        }
        metrics = {
            "total_cost_of_ownership": self._extract_total_cost_of_ownership(**params.get("total_cost_of_ownership", {})),
            "depreciation_rate": self._extract_depreciation_rate(**params.get("depreciation_rate", {})),
            "fuel_efficiency": self._extract_fuel_efficiency(**params.get("fuel_efficiency", {})),
            "utilization_rate": self._extract_utilization_rate(**params.get("utilization_rate", {})),
            "downtime_rate": self._extract_downtime_rate(**params.get("downtime_rate", {})),
            "defect_rate": self._extract_defect_rate(**params.get("defect_rate", {})),
            "warranty_claim_rate": self._extract_warranty_claim_rate(**params.get("warranty_claim_rate", {})),
            "recall_rate": self._extract_recall_rate(**params.get("recall_rate", {})),
        }
        compliance_flags = {
            "nhtsa": self._check_nhtsa(text),
            "epa_carb": self._check_epa_carb(text),
            "euro_ncap": self._check_euro_ncap(text),
            "supplier_ppap": self._check_supplier_ppap(text),
            "right_to_repair": self._check_right_to_repair(text),
        }
        risk_scores = {
            "safety_risk": self._score_safety_risk(text),
            "supply_chain_risk": self._score_supply_chain_risk(text),
            "reputation_risk": self._score_reputation_risk(text),
            "compliance_risk": self._score_compliance_risk(text),
            "financial_risk": self._score_financial_risk(text),
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
                "vehicle_type": self._extract_vehicle_type(text),
            },
        }

    def _extract_vehicle_type(self, text: str) -> Optional[str]:
        """Best-effort extraction of vehicle type."""
        pattern = r"(?:vehicle type|vehicle_type)[:\s]+([A-Z][A-Za-z0-9\s&.,-]{2,60})"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            return match.group(1).strip()
        return None

    # ------------------------------------------------------------------
    # ENTITY EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_vins(self, text: str) -> List[Dict]:
        """Extract vins from text."""
        found = []
        for match in re.finditer(r"\b([A-HJ-NPR-Z0-9]{17})\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "vins",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_makes(self, text: str) -> List[Dict]:
        """Extract makes from text."""
        found = []
        for match in re.finditer(r"\b(Toyota|Ford|BMW|Mercedes|Mercedes-Benz|Tesla|Honda|Volkswagen|VW|Hyundai|Chevrolet|GM|Nissan|Audi|Lexus|Kia|Subaru|Mazda|Jeep|Ram|GMC|Cadillac|Lincoln|Infiniti|Acura|Volvo|Porsche|Jaguar|Land Rover|Mini|Fiat|Chrysler|Dodge)\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "makes",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_models(self, text: str) -> List[Dict]:
        """Extract models from text."""
        found = []
        for match in re.finditer(r"\b(Camry|Corolla|F-150|Silverado|3 Series|5 Series|C-Class|E-Class|Model 3|Model Y|Civic|Accord|Golf|Jetta|Tiguan|Elantra|Sonata|Altima|Sentra|Rogue|CR-V|RAV4|Highlander|Silverado|Tahoe|Explorer|Mustang|Wrangler|Cherokee|Outback|Forester|CX-5|3|CX-9|Ranger|Tundra|Tacoma|Sierra|Escalade|Navigator|Q5|X5|X3|GLE|GLC)\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "models",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_model_years(self, text: str) -> List[Dict]:
        """Extract model years from text."""
        found = []
        for match in re.finditer(r"\b(MY\s*)?(20\d{2}|19\d{2})\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "model_years",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_mileage(self, text: str) -> List[Dict]:
        """Extract mileage from text."""
        found = []
        for match in re.finditer(r"(\d{1,3},\d{3})\s*(miles|km|mi|kilometers)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "mileage",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_parts_numbers(self, text: str) -> List[Dict]:
        """Extract parts numbers from text."""
        found = []
        for match in re.finditer(r"(?:oem part|part number|aftermarket sku)\s*#?\s*([A-Z0-9\-]{6,12})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "parts_numbers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_dealers(self, text: str) -> List[Dict]:
        """Extract dealers from text."""
        found = []
        for match in re.finditer(r"(?:dealer|dealership|service center|authorized repair|franchise)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "dealers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_suppliers(self, text: str) -> List[Dict]:
        """Extract suppliers from text."""
        found = []
        for match in re.finditer(r"(?:tier 1|tier 2|oem supplier|component manufacturer|supplier)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "suppliers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    # ------------------------------------------------------------------
    # METRICS & FORMULA EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_total_cost_of_ownership(self, purchase_price=None, fuel=None, maintenance=None, insurance=None, depreciation=None) -> Dict[str, Any]:
        """Calculate total cost of ownership."""
        try:
            value = (purchase_price + fuel + maintenance + insurance + depreciation) if purchase_price is not None else None
            if value is None:
                return {"name": "total_cost_of_ownership", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "total_cost_of_ownership", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "total_cost_of_ownership", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_depreciation_rate(self, initial_value=None, current_value=None, years=None) -> Dict[str, Any]:
        """Calculate depreciation rate."""
        try:
            value = self._safe_divide(self._safe_divide(initial_value - current_value, initial_value), years, scale=100) if (initial_value is not None and current_value is not None and years is not None) else None
            if value is None:
                return {"name": "depreciation_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "depreciation_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "depreciation_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_fuel_efficiency(self, distance=None, fuel_consumed=None) -> Dict[str, Any]:
        """Calculate fuel efficiency."""
        try:
            value = self._safe_divide(distance, fuel_consumed) if (distance is not None and fuel_consumed is not None) else None
            if value is None:
                return {"name": "fuel_efficiency", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "fuel_efficiency", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "fuel_efficiency", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_utilization_rate(self, operating_hours=None, available_hours=None) -> Dict[str, Any]:
        """Calculate utilization rate."""
        try:
            value = self._safe_divide(operating_hours, available_hours, scale=100) if (operating_hours is not None and available_hours is not None) else None
            if value is None:
                return {"name": "utilization_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "utilization_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "utilization_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_downtime_rate(self, downtime_hours=None, total_hours=None) -> Dict[str, Any]:
        """Calculate downtime rate."""
        try:
            value = self._safe_divide(downtime_hours, total_hours, scale=100) if (downtime_hours is not None and total_hours is not None) else None
            if value is None:
                return {"name": "downtime_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "downtime_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "downtime_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_defect_rate(self, defective_units=None, total_units=None) -> Dict[str, Any]:
        """Calculate defect rate."""
        try:
            value = self._safe_divide(defective_units, total_units, scale=1_000_000) if (defective_units is not None and total_units is not None) else None
            if value is None:
                return {"name": "defect_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "defect_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "defect_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_warranty_claim_rate(self, claims=None, units_sold=None) -> Dict[str, Any]:
        """Calculate warranty claim rate."""
        try:
            value = self._safe_divide(claims, units_sold, scale=100) if (claims is not None and units_sold is not None) else None
            if value is None:
                return {"name": "warranty_claim_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "warranty_claim_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "warranty_claim_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_recall_rate(self, recalled_units=None, total_produced=None) -> Dict[str, Any]:
        """Calculate recall rate."""
        try:
            value = self._safe_divide(recalled_units, total_produced, scale=100) if (recalled_units is not None and total_produced is not None) else None
            if value is None:
                return {"name": "recall_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "recall_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "recall_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    # ------------------------------------------------------------------
    # REGULATORY & COMPLIANCE CHECKING (private)
    # ------------------------------------------------------------------

    def _check_nhtsa(self, text: str) -> Dict[str, Any]:
        """Check nhtsa compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["nhtsa"] if kw in text.lower()]
        return {
            "regulation": "nhtsa",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_epa_carb(self, text: str) -> Dict[str, Any]:
        """Check epa carb compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["epa_carb"] if kw in text.lower()]
        return {
            "regulation": "epa_carb",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_euro_ncap(self, text: str) -> Dict[str, Any]:
        """Check euro ncap compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["euro_ncap"] if kw in text.lower()]
        return {
            "regulation": "euro_ncap",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_supplier_ppap(self, text: str) -> Dict[str, Any]:
        """Check supplier ppap compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["supplier_ppap"] if kw in text.lower()]
        return {
            "regulation": "supplier_ppap",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_right_to_repair(self, text: str) -> Dict[str, Any]:
        """Check right to repair compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["right_to_repair"] if kw in text.lower()]
        return {
            "regulation": "right_to_repair",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    # ------------------------------------------------------------------
    # RISK SCORING (private)
    # ------------------------------------------------------------------

    def _score_safety_risk(self, text: str) -> RiskScore:
        """Score safety risk."""
        data = _rk.check_risk_keywords(text).get("safety_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="safety_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_supply_chain_risk(self, text: str) -> RiskScore:
        """Score supply chain risk."""
        data = _rk.check_risk_keywords(text).get("supply_chain_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="supply_chain_risk",
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

    def _score_financial_risk(self, text: str) -> RiskScore:
        """Score financial risk."""
        data = _rk.check_risk_keywords(text).get("financial_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="financial_risk",
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
