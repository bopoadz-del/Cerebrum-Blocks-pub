"""Agriculture Block v2 - TypedBlock implementation

This is the v2 implementation that:
- Extends TypedBlock instead of UniversalContainer
- Accepts TextContent input (from pdf_v2, ocr_v2, etc.)
- Outputs AgricultureAnalysis type
- Has a single process() entry point instead of action routing
- Internal methods are private (_ prefixed)
- Uses deterministic regex + math, no LLM calls, no external APIs
"""

import re
from typing import Any, Dict, List, Optional

from app.core.domain_block_v2 import DomainBlockV2
from app.core.schema_registry import TextContent, AgricultureAnalysis
from app.core.agriculture_types import RiskScore

from app.core.agriculture_knowledge import AgricultureKnowledge, COMPLIANCE_KEYWORDS
from app.core.http_errors import error_kind

_rk = AgricultureKnowledge()


class AgricultureBlockV2(DomainBlockV2):
    """
    Agriculture Block v2 - TypedBlock implementation for agriculture document analysis.

    Input: TextContent (extracted document text)
    Output: AgricultureAnalysis (entities, metrics, compliance flags, risk scores)
    """

    name = "agriculture_v2"
    version = "2.0"
    description = "Agriculture document analysis with typed input/output"
    layer = 3
    tags = ["domain", "agriculture", "v2"]
    requires = []

    default_config = {
        "confidence_threshold": 0.85,
    }

    input_schema = TextContent
    output_schema = AgricultureAnalysis

    accepted_input_types = ["TextContent", "PDFContent"]
    produced_output_types = ["AgricultureAnalysis"]

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste agriculture document text...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "yield_per_acre", "type": "number", "label": "Yield / Acre"},
                {"name": "protein_content", "type": "number", "label": "Protein %"},
                {"name": "feed_conversion_ratio", "type": "number", "label": "FCR"},
                {"name": "cost_per_acre", "type": "number", "label": "Cost / Acre"},
                {"name": "weather_risk", "type": "number", "label": "Weather Risk"},
                {"name": "market_risk", "type": "number", "label": "Market Risk"},
                {"name": "regulatory_risk", "type": "number", "label": "Regulatory Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze Crop Report", "prompt": "Analyze this crop report"},
            {"icon": "🌱", "label": "Check Organic Compliance", "prompt": "Check this document for organic compliance"},
            {"icon": "⚠️", "label": "Score Agriculture Risks", "prompt": "Score agriculture risks for this document"},
            {"icon": "🔍", "label": "Extract Yields & Inputs", "prompt": "Extract yields and inputs from this document"},
        ],
    }

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Main entry point - analyze agriculture document text."""
        params = params or {}

        text = self._extract_text(input_data)
        if not text:
            return self._empty_analysis("No text provided")

        custom_rules = params.get("custom_rules") or params.get("rules")
        if custom_rules:
            _rk.set_custom_rules(custom_rules)

        document_type = params.get("document_type") or params.get("analysis_type") or self._detect_document_type(text)

        if document_type == "crop_report":
            return await self._analyze_crop_report(text, params)
        if document_type == "soil_test":
            return await self._analyze_soil_test(text, params)
        if document_type == "pesticide_application":
            return await self._analyze_pesticide_application(text, params)
        if document_type == "organic_certification":
            return await self._analyze_organic_certification(text, params)
        if document_type == "livestock_record":
            return await self._analyze_livestock_record(text, params)
        if document_type == "grain_contract":
            return await self._analyze_grain_contract(text, params)
        if document_type == "irrigation_log":
            return await self._analyze_irrigation_log(text, params)
        if document_type == "food_safety_audit":
            return await self._analyze_food_safety_audit(text, params)

        return await self._analyze_generic(text, params)

    # ------------------------------------------------------------------
    # TEXT EXTRACTION
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DOCUMENT TYPE DETECTION
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        """Auto-detect agriculture document type from content."""
        text_lower = text[:5000].lower()

        if any(kw in text_lower for kw in ['yield', 'harvest', 'acreage', 'planting', 'sowing', 'germination', 'growth stage', 'usda']):
            return "crop_report"
        if any(kw in text_lower for kw in ['soil', 'ph', 'npk', 'organic matter', 'salinity', 'texture', 'compaction', 'micronutrients']):
            return "soil_test"
        if any(kw in text_lower for kw in ['pesticide', 'herbicide', 'fungicide', 'insecticide', 'application rate', 'phi', 'rei']):
            return "pesticide_application"
        if any(kw in text_lower for kw in ['organic', 'nop', 'usda organic', 'certification', 'inspection', 'buffer zone', 'prohibited substances']):
            return "organic_certification"
        if any(kw in text_lower for kw in ['herd', 'flock', 'vaccination', 'breeding', 'calving', 'farrowing', 'weight gain', 'feed conversion']):
            return "livestock_record"
        if any(kw in text_lower for kw in ['grain', 'futures', 'basis', 'delivery', 'elevator', 'moisture', 'test weight', 'dockage']):
            return "grain_contract"
        if any(kw in text_lower for kw in ['irrigation', 'water usage', 'drip', 'sprinkler', 'pivot', 'et', 'soil moisture', 'deficit']):
            return "irrigation_log"
        if any(kw in text_lower for kw in ['gap', 'gmp', 'haccp', 'fsma', 'traceback', 'recall', 'contamination', 'temperature log']):
            return "food_safety_audit"

        return "generic"

    # ------------------------------------------------------------------
    # ANALYSIS METHODS (private)
    # ------------------------------------------------------------------

    async def _analyze_crop_report(self, text: str, params: Dict) -> Dict:
        """Analyze crop report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "crop_report"
        return self._finalize_result(result, params)

    async def _analyze_soil_test(self, text: str, params: Dict) -> Dict:
        """Analyze soil test text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "soil_test"
        return self._finalize_result(result, params)

    async def _analyze_pesticide_application(self, text: str, params: Dict) -> Dict:
        """Analyze pesticide application text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "pesticide_application"
        return self._finalize_result(result, params)

    async def _analyze_organic_certification(self, text: str, params: Dict) -> Dict:
        """Analyze organic certification text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "organic_certification"
        return self._finalize_result(result, params)

    async def _analyze_livestock_record(self, text: str, params: Dict) -> Dict:
        """Analyze livestock record text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "livestock_record"
        return self._finalize_result(result, params)

    async def _analyze_grain_contract(self, text: str, params: Dict) -> Dict:
        """Analyze grain contract text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "grain_contract"
        return self._finalize_result(result, params)

    async def _analyze_irrigation_log(self, text: str, params: Dict) -> Dict:
        """Analyze irrigation log text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "irrigation_log"
        return self._finalize_result(result, params)

    async def _analyze_food_safety_audit(self, text: str, params: Dict) -> Dict:
        """Analyze food safety audit text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "food_safety_audit"
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
            "crop_types": self._extract_crop_types(text),
            "varieties": self._extract_varieties(text),
            "field_ids": self._extract_field_ids(text),
            "acreage": self._extract_acreage(text),
            "yield_per_acre": self._extract_yield_per_acre(text),
            "fertilizer_rates": self._extract_fertilizer_rates(text),
            "pesticide_names": self._extract_pesticide_names(text),
            "livestock_counts": self._extract_livestock_counts(text),
        }
        metrics = {
            "yield_per_acre": self._calculate_yield_per_acre(**params.get("yield_per_acre", {})),
            "moisture_adjusted_yield": self._extract_moisture_adjusted_yield(**params.get("moisture_adjusted_yield", {})),
            "protein_content": self._extract_protein_content(**params.get("protein_content", {})),
            "feed_conversion_ratio": self._extract_feed_conversion_ratio(**params.get("feed_conversion_ratio", {})),
            "weaning_weight": self._extract_weaning_weight(**params.get("weaning_weight", {})),
            "water_use_efficiency": self._extract_water_use_efficiency(**params.get("water_use_efficiency", {})),
            "nutrient_use_efficiency": self._extract_nutrient_use_efficiency(**params.get("nutrient_use_efficiency", {})),
            "cost_per_acre": self._extract_cost_per_acre(**params.get("cost_per_acre", {})),
        }
        compliance_flags = {
            "usda_organic": self._check_usda_organic(text),
            "fsma": self._check_fsma(text),
            "epa_pesticide": self._check_epa_pesticide(text),
            "mrl": self._check_mrl(text),
            "animal_welfare": self._check_animal_welfare(text),
        }
        risk_scores = {
            "weather_risk": self._score_weather_risk(text),
            "pest_disease_risk": self._score_pest_disease_risk(text),
            "market_risk": self._score_market_risk(text),
            "regulatory_risk": self._score_regulatory_risk(text),
            "sustainability_risk": self._score_sustainability_risk(text),
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
                "farm_name": self._extract_farm_name(text),
            },
        }

    def _extract_farm_name(self, text: str) -> Optional[str]:
        """Best-effort extraction of farm name."""
        pattern = r"(?:farm name|farm_name)[:\s]+([A-Z][A-Za-z0-9\s&.,-]{2,60})"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            return match.group(1).strip()
        return None

    # ------------------------------------------------------------------
    # ENTITY EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_crop_types(self, text: str) -> List[Dict]:
        """Extract crop types from text."""
        found = []
        for match in re.finditer(r"\b(wheat|corn|soybeans|soybean|rice|cotton|sugarcane|barley|canola|oats|sorghum|alfalfa|potato|tomato)\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "crop_types",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_varieties(self, text: str) -> List[Dict]:
        """Extract varieties from text."""
        found = []
        for match in re.finditer(r"(?:variety|cultivar|hybrid|gmo|seed brand|trait)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s\-]+)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "varieties",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_field_ids(self, text: str) -> List[Dict]:
        """Extract field ids from text."""
        found = []
        for match in re.finditer(r"(?:field|block|section|tract|fsa farm)\s*#?\s*(\d{1,4})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "field_ids",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_acreage(self, text: str) -> List[Dict]:
        """Extract acreage from text."""
        found = []
        for match in re.finditer(r"(\d{1,4}(?:\.\d+)?)\s*(acres|acre|ha|hectares|hectare)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "acreage",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_yield_per_acre(self, text: str) -> List[Dict]:
        """Extract yield per acre from text."""
        found = []
        for match in re.finditer(r"(\d{1,4})\s*(?:bushels|tons|kg|lbs)?\s*per\s*(acre|ha)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "yield_per_acre",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_fertilizer_rates(self, text: str) -> List[Dict]:
        """Extract fertilizer rates from text."""
        found = []
        for match in re.finditer(r"(\d{1,3})\s*(?:lbs|kg|tons)?\s*(N|P|K|NPK)\s*per\s*(acre|ha)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "fertilizer_rates",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_pesticide_names(self, text: str) -> List[Dict]:
        """Extract pesticide names from text."""
        found = []
        for match in re.finditer(r"\b(Roundup|atrazine|glyphosate|2,4-D|dicamba|chlorpyrifos|neonicotinoid|paraguat)\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "pesticide_names",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_livestock_counts(self, text: str) -> List[Dict]:
        """Extract livestock counts from text."""
        found = []
        for match in re.finditer(r"(\d{1,5})\s*(head|cattle|pigs|sheep|chickens|birds|hogs|cows)\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "livestock_counts",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    # ------------------------------------------------------------------
    # METRICS & FORMULA EXTRACTION (private)
    # ------------------------------------------------------------------

    def _calculate_yield_per_acre(self, total_yield=None, total_acres=None) -> Dict[str, Any]:
        """Calculate yield per acre."""
        try:
            value = self._safe_divide(total_yield, total_acres) if (total_yield is not None and total_acres is not None) else None
            if value is None:
                return {"name": "yield_per_acre", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "yield_per_acre", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "yield_per_acre", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_moisture_adjusted_yield(self, yield_at_moisture=None, moisture_percent=None) -> Dict[str, Any]:
        """Calculate moisture adjusted yield."""
        try:
            value = self._safe_divide(yield_at_moisture * (1 - moisture_percent / 100), (1 - 0.155)) if (yield_at_moisture is not None and moisture_percent is not None) else None
            if value is None:
                return {"name": "moisture_adjusted_yield", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "moisture_adjusted_yield", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "moisture_adjusted_yield", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_protein_content(self, protein_weight=None, total_sample_weight=None) -> Dict[str, Any]:
        """Calculate protein content."""
        try:
            value = self._safe_divide(protein_weight, total_sample_weight, scale=100) if (protein_weight is not None and total_sample_weight is not None) else None
            if value is None:
                return {"name": "protein_content", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "protein_content", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "protein_content", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_feed_conversion_ratio(self, feed_consumed=None, weight_gain=None) -> Dict[str, Any]:
        """Calculate feed conversion ratio."""
        try:
            value = self._safe_divide(feed_consumed, weight_gain) if (feed_consumed is not None and weight_gain is not None) else None
            if value is None:
                return {"name": "feed_conversion_ratio", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "feed_conversion_ratio", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "feed_conversion_ratio", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_weaning_weight(self, piglet_weight=None, age_days=None) -> Dict[str, Any]:
        """Calculate weaning weight."""
        try:
            value = self._safe_divide(piglet_weight, age_days, scale=21) if (piglet_weight is not None and age_days is not None) else None
            if value is None:
                return {"name": "weaning_weight", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "weaning_weight", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "weaning_weight", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_water_use_efficiency(self, total_yield=None, water_applied=None) -> Dict[str, Any]:
        """Calculate water use efficiency."""
        try:
            value = self._safe_divide(total_yield, water_applied) if (total_yield is not None and water_applied is not None) else None
            if value is None:
                return {"name": "water_use_efficiency", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "water_use_efficiency", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "water_use_efficiency", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_nutrient_use_efficiency(self, total_yield=None, nutrient_applied=None) -> Dict[str, Any]:
        """Calculate nutrient use efficiency."""
        try:
            value = self._safe_divide(total_yield, nutrient_applied) if (total_yield is not None and nutrient_applied is not None) else None
            if value is None:
                return {"name": "nutrient_use_efficiency", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "nutrient_use_efficiency", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "nutrient_use_efficiency", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_cost_per_acre(self, total_cost=None, acres=None) -> Dict[str, Any]:
        """Calculate cost per acre."""
        try:
            value = self._safe_divide(total_cost, acres) if (total_cost is not None and acres is not None) else None
            if value is None:
                return {"name": "cost_per_acre", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "cost_per_acre", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "cost_per_acre", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    # ------------------------------------------------------------------
    # REGULATORY & COMPLIANCE CHECKING (private)
    # ------------------------------------------------------------------

    def _check_usda_organic(self, text: str) -> Dict[str, Any]:
        """Check usda organic compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["usda_organic"] if kw in text.lower()]
        return {
            "regulation": "usda_organic",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_fsma(self, text: str) -> Dict[str, Any]:
        """Check fsma compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["fsma"] if kw in text.lower()]
        return {
            "regulation": "fsma",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_epa_pesticide(self, text: str) -> Dict[str, Any]:
        """Check epa pesticide compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["epa_pesticide"] if kw in text.lower()]
        return {
            "regulation": "epa_pesticide",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_mrl(self, text: str) -> Dict[str, Any]:
        """Check mrl compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["mrl"] if kw in text.lower()]
        return {
            "regulation": "mrl",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_animal_welfare(self, text: str) -> Dict[str, Any]:
        """Check animal welfare compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["animal_welfare"] if kw in text.lower()]
        return {
            "regulation": "animal_welfare",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    # ------------------------------------------------------------------
    # RISK SCORING (private)
    # ------------------------------------------------------------------

    def _score_weather_risk(self, text: str) -> RiskScore:
        """Score weather risk."""
        data = _rk.check_risk_keywords(text).get("weather_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="weather_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_pest_disease_risk(self, text: str) -> RiskScore:
        """Score pest disease risk."""
        data = _rk.check_risk_keywords(text).get("pest_disease_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="pest_disease_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_market_risk(self, text: str) -> RiskScore:
        """Score market risk."""
        data = _rk.check_risk_keywords(text).get("market_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="market_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_regulatory_risk(self, text: str) -> RiskScore:
        """Score regulatory risk."""
        data = _rk.check_risk_keywords(text).get("regulatory_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="regulatory_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_sustainability_risk(self, text: str) -> RiskScore:
        """Score sustainability risk."""
        data = _rk.check_risk_keywords(text).get("sustainability_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="sustainability_risk",
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
