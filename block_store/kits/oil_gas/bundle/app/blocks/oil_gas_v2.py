"""OilGas Block v2 - TypedBlock implementation

This is the v2 implementation that:
- Extends TypedBlock instead of UniversalContainer
- Accepts TextContent input (from pdf_v2, ocr_v2, etc.)
- Outputs OilGasAnalysis type
- Has a single process() entry point instead of action routing
- Internal methods are private (_ prefixed)
- Uses deterministic regex + math, no LLM calls, no external APIs
"""

import re
from typing import Any, Dict, List, Optional

from app.core.domain_block_v2 import DomainBlockV2
from app.core.schema_registry import TextContent, OilGasAnalysis
from app.core.oil_gas_types import RiskScore

from app.core.oil_gas_knowledge import OilGasKnowledge, COMPLIANCE_KEYWORDS
from app.core.http_errors import error_kind

_rk = OilGasKnowledge()


class OilGasBlockV2(DomainBlockV2):
    """
    OilGas Block v2 - TypedBlock implementation for oil_gas document analysis.

    Input: TextContent (extracted document text)
    Output: OilGasAnalysis (entities, metrics, compliance flags, risk scores)
    """

    name = "oil_gas_v2"
    version = "2.0"
    description = "OilGas document analysis with typed input/output"
    layer = 3
    tags = ["domain", "oil_gas", "v2"]
    requires = []

    default_config = {
        "confidence_threshold": 0.85,
    }

    input_schema = TextContent
    output_schema = OilGasAnalysis

    accepted_input_types = ["TextContent", "PDFContent"]
    produced_output_types = ["OilGasAnalysis"]

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste oil & gas document text...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "rop", "type": "number", "label": "ROP"},
                {"name": "water_cut", "type": "number", "label": "Water Cut %"},
                {"name": "gas_oil_ratio", "type": "number", "label": "GOR"},
                {"name": "recovery_factor", "type": "number", "label": "Recovery Factor %"},
                {"name": "well_control_risk", "type": "number", "label": "Well Control Risk"},
                {"name": "environmental_risk", "type": "number", "label": "Environmental Risk"},
                {"name": "regulatory_risk", "type": "number", "label": "Regulatory Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze Well Log", "prompt": "Analyze this well log"},
            {"icon": "🛢️", "label": "Check BSEE Compliance", "prompt": "Check this document for BSEE compliance"},
            {"icon": "⚠️", "label": "Score Oil & Gas Risks", "prompt": "Score oil and gas risks for this document"},
            {"icon": "🔍", "label": "Extract Wells & Formations", "prompt": "Extract wells and formations from this document"},
        ],
    }

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Main entry point - analyze oil_gas document text."""
        params = params or {}

        text = self._extract_text(input_data)
        if not text:
            return self._empty_analysis("No text provided")

        custom_rules = params.get("custom_rules") or params.get("rules")
        if custom_rules:
            _rk.set_custom_rules(custom_rules)

        document_type = params.get("document_type") or params.get("analysis_type") or self._detect_document_type(text)

        if document_type == "well_log":
            return await self._analyze_well_log(text, params)
        if document_type == "drilling_report":
            return await self._analyze_drilling_report(text, params)
        if document_type == "production_report":
            return await self._analyze_production_report(text, params)
        if document_type == "safety_incident":
            return await self._analyze_safety_incident(text, params)
        if document_type == "environmental_impact":
            return await self._analyze_environmental_impact(text, params)
        if document_type == "joint_operating_agreement":
            return await self._analyze_joint_operating_agreement(text, params)
        if document_type == "reserves_report":
            return await self._analyze_reserves_report(text, params)
        if document_type == "pipeline_inspection":
            return await self._analyze_pipeline_inspection(text, params)

        return await self._analyze_generic(text, params)

    # ------------------------------------------------------------------
    # TEXT EXTRACTION
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DOCUMENT TYPE DETECTION
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        """Auto-detect oil_gas document type from content."""
        text_lower = text[:5000].lower()

        if any(kw in text_lower for kw in ['well log', 'gamma ray', 'resistivity', 'porosity', 'permeability', 'formation', 'depth', 'md', 'tvd']):
            return "well_log"
        if any(kw in text_lower for kw in ['drilling', 'rop', 'wob', 'rpm', 'mud weight', 'kick', 'loss', 'stuck pipe', 'non-productive time']):
            return "drilling_report"
        if any(kw in text_lower for kw in ['production', 'boe', 'bbl', 'mcf', 'choke', 'wellhead pressure', 'water cut', 'gas oil ratio']):
            return "production_report"
        if any(kw in text_lower for kw in ['incident', 'spill', 'blowout', 'fire', 'explosion', 'h2s', 'lopc', 'near miss', 'stop card']):
            return "safety_incident"
        if any(kw in text_lower for kw in ['eia', 'environmental impact', 'emissions', 'flaring', 'venting', 'spill', 'remediation', 'epa']):
            return "environmental_impact"
        if any(kw in text_lower for kw in ['joa', 'joint venture', 'working interest', 'non-operator', 'afe', 'copas', 'overhead']):
            return "joint_operating_agreement"
        if any(kw in text_lower for kw in ['reserves', 'spe-prms', '1p', '2p', '3p', 'proved', 'probable', 'possible', 'npv10', 'sec']):
            return "reserves_report"
        if any(kw in text_lower for kw in ['pipeline', 'ili', 'smart pig', 'corrosion', 'dent', 'crack', 'maop', 'hydrotest', 'cathodic protection']):
            return "pipeline_inspection"

        return "generic"

    # ------------------------------------------------------------------
    # ANALYSIS METHODS (private)
    # ------------------------------------------------------------------

    async def _analyze_well_log(self, text: str, params: Dict) -> Dict:
        """Analyze well log text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "well_log"
        return self._finalize_result(result, params)

    async def _analyze_drilling_report(self, text: str, params: Dict) -> Dict:
        """Analyze drilling report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "drilling_report"
        return self._finalize_result(result, params)

    async def _analyze_production_report(self, text: str, params: Dict) -> Dict:
        """Analyze production report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "production_report"
        return self._finalize_result(result, params)

    async def _analyze_safety_incident(self, text: str, params: Dict) -> Dict:
        """Analyze safety incident text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "safety_incident"
        return self._finalize_result(result, params)

    async def _analyze_environmental_impact(self, text: str, params: Dict) -> Dict:
        """Analyze environmental impact text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "environmental_impact"
        return self._finalize_result(result, params)

    async def _analyze_joint_operating_agreement(self, text: str, params: Dict) -> Dict:
        """Analyze joint operating agreement text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "joint_operating_agreement"
        return self._finalize_result(result, params)

    async def _analyze_reserves_report(self, text: str, params: Dict) -> Dict:
        """Analyze reserves report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "reserves_report"
        return self._finalize_result(result, params)

    async def _analyze_pipeline_inspection(self, text: str, params: Dict) -> Dict:
        """Analyze pipeline inspection text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "pipeline_inspection"
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
            "well_names": self._extract_well_names(text),
            "formation_names": self._extract_formation_names(text),
            "rig_names": self._extract_rig_names(text),
            "contractor_names": self._extract_contractor_names(text),
            "field_names": self._extract_field_names(text),
            "depths": self._extract_depths(text),
            "pressures": self._extract_pressures(text),
            "temperatures": self._extract_temperatures(text),
        }
        metrics = {
            "rop": self._extract_rop(**params.get("rop", {})),
            "npt_percentage": self._extract_npt_percentage(**params.get("npt_percentage", {})),
            "water_cut": self._extract_water_cut(**params.get("water_cut", {})),
            "gas_oil_ratio": self._extract_gas_oil_ratio(**params.get("gas_oil_ratio", {})),
            "recovery_factor": self._extract_recovery_factor(**params.get("recovery_factor", {})),
            "npv_10": self._extract_npv_10(**params.get("npv_10", {})),
            "finding_cost": self._extract_finding_cost(**params.get("finding_cost", {})),
            "lifting_cost": self._extract_lifting_cost(**params.get("lifting_cost", {})),
        }
        compliance_flags = {
            "osha": self._check_osha(text),
            "bsee": self._check_bsee(text),
            "epa": self._check_epa(text),
            "phmsa": self._check_phmsa(text),
            "local_content": self._check_local_content(text),
        }
        risk_scores = {
            "well_control_risk": self._score_well_control_risk(text),
            "environmental_risk": self._score_environmental_risk(text),
            "regulatory_risk": self._score_regulatory_risk(text),
            "market_risk": self._score_market_risk(text),
            "operational_risk": self._score_operational_risk(text),
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
                "basin_name": self._extract_basin_name(text),
            },
        }

    def _extract_basin_name(self, text: str) -> Optional[str]:
        """Best-effort extraction of basin name."""
        pattern = r"(?:basin name|basin_name)[:\s]+([A-Z][A-Za-z0-9\s&.,-]{2,60})"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            return match.group(1).strip()
        return None

    # ------------------------------------------------------------------
    # ENTITY EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_well_names(self, text: str) -> List[Dict]:
        """Extract well names from text."""
        found = []
        for match in re.finditer(r"(?:well\s+\d{1,3}-[A-Z]{1,2}-\d{1,3}|API\s+\d{2}-\d{3}-\d{5}-\d{2}|lease\s+[A-Za-z0-9\s]+)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "well_names",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_formation_names(self, text: str) -> List[Dict]:
        """Extract formation names from text."""
        found = []
        for match in re.finditer(r"(?:formation|reservoir|zone|pay|sandstone|shale|limestone|dolomite)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s\-]+)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "formation_names",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_rig_names(self, text: str) -> List[Dict]:
        """Extract rig names from text."""
        found = []
        for match in re.finditer(r"(?:rig|drilling unit|jack-up|semi-sub|drillship|land rig|platform)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s\-]+)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "rig_names",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_contractor_names(self, text: str) -> List[Dict]:
        """Extract contractor names from text."""
        found = []
        for match in re.finditer(r"(?:contractor|service company|Schlumberger|Halliburton|Baker Hughes|Weatherford)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "contractor_names",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_field_names(self, text: str) -> List[Dict]:
        """Extract field names from text."""
        found = []
        for match in re.finditer(r"(?:field|block|concession|license|psc|lease|unit|participating area)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s\-]+)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "field_names",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_depths(self, text: str) -> List[Dict]:
        """Extract depths from text."""
        found = []
        for match in re.finditer(r"(\d{1,5})\s*(ft|m|MD|TVD|TVDSS|KB|DF)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "depths",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_pressures(self, text: str) -> List[Dict]:
        """Extract pressures from text."""
        found = []
        for match in re.finditer(r"(\d{1,5})\s*(psi|bar|MPa|psig|psia)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "pressures",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_temperatures(self, text: str) -> List[Dict]:
        """Extract temperatures from text."""
        found = []
        for match in re.finditer(r"(\d{1,3})\s*(°F|°C|F|C)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "temperatures",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    # ------------------------------------------------------------------
    # METRICS & FORMULA EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_rop(self, total_drilled_length=None, drilling_time=None) -> Dict[str, Any]:
        """Calculate rop."""
        try:
            value = self._safe_divide(total_drilled_length, drilling_time) if (total_drilled_length is not None and drilling_time is not None) else None
            if value is None:
                return {"name": "rop", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "rop", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "rop", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_npt_percentage(self, npt_hours=None, total_hours=None) -> Dict[str, Any]:
        """Calculate npt percentage."""
        try:
            value = self._safe_divide(npt_hours, total_hours, scale=100) if (npt_hours is not None and total_hours is not None) else None
            if value is None:
                return {"name": "npt_percentage", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "npt_percentage", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "npt_percentage", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_water_cut(self, water_production=None, total_liquid_production=None) -> Dict[str, Any]:
        """Calculate water cut."""
        try:
            value = self._safe_divide(water_production, total_liquid_production, scale=100) if (water_production is not None and total_liquid_production is not None) else None
            if value is None:
                return {"name": "water_cut", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "water_cut", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "water_cut", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_gas_oil_ratio(self, gas_production=None, oil_production=None) -> Dict[str, Any]:
        """Calculate gas oil ratio."""
        try:
            value = self._safe_divide(gas_production, oil_production) if (gas_production is not None and oil_production is not None) else None
            if value is None:
                return {"name": "gas_oil_ratio", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "gas_oil_ratio", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "gas_oil_ratio", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_recovery_factor(self, recovered=None, original_in_place=None) -> Dict[str, Any]:
        """Calculate recovery factor."""
        try:
            value = self._safe_divide(recovered, original_in_place, scale=100) if (recovered is not None and original_in_place is not None) else None
            if value is None:
                return {"name": "recovery_factor", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "recovery_factor", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "recovery_factor", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_npv_10(self, cash_flows=None, discount_rate=None) -> Dict[str, Any]:
        """Calculate npv 10."""
        try:
            value = sum(self._safe_divide(cf, (1 + 0.10) ** i) for i, cf in enumerate(cash_flows or [])) if cash_flows else None
            if value is None:
                return {"name": "npv_10", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "npv_10", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "npv_10", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_finding_cost(self, exploration_cost=None, reserves_added=None) -> Dict[str, Any]:
        """Calculate finding cost."""
        try:
            value = self._safe_divide(exploration_cost, reserves_added) if (exploration_cost is not None and reserves_added is not None) else None
            if value is None:
                return {"name": "finding_cost", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "finding_cost", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "finding_cost", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_lifting_cost(self, operating_cost=None, production_volume=None) -> Dict[str, Any]:
        """Calculate lifting cost."""
        try:
            value = self._safe_divide(operating_cost, production_volume) if (operating_cost is not None and production_volume is not None) else None
            if value is None:
                return {"name": "lifting_cost", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "lifting_cost", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "lifting_cost", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    # ------------------------------------------------------------------
    # REGULATORY & COMPLIANCE CHECKING (private)
    # ------------------------------------------------------------------

    def _check_osha(self, text: str) -> Dict[str, Any]:
        """Check osha compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["osha"] if kw in text.lower()]
        return {
            "regulation": "osha",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_bsee(self, text: str) -> Dict[str, Any]:
        """Check bsee compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["bsee"] if kw in text.lower()]
        return {
            "regulation": "bsee",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_epa(self, text: str) -> Dict[str, Any]:
        """Check epa compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["epa"] if kw in text.lower()]
        return {
            "regulation": "epa",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_phmsa(self, text: str) -> Dict[str, Any]:
        """Check phmsa compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["phmsa"] if kw in text.lower()]
        return {
            "regulation": "phmsa",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_local_content(self, text: str) -> Dict[str, Any]:
        """Check local content compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["local_content"] if kw in text.lower()]
        return {
            "regulation": "local_content",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    # ------------------------------------------------------------------
    # RISK SCORING (private)
    # ------------------------------------------------------------------

    def _score_well_control_risk(self, text: str) -> RiskScore:
        """Score well control risk."""
        data = _rk.check_risk_keywords(text).get("well_control_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="well_control_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_environmental_risk(self, text: str) -> RiskScore:
        """Score environmental risk."""
        data = _rk.check_risk_keywords(text).get("environmental_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="environmental_risk",
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

    def _score_operational_risk(self, text: str) -> RiskScore:
        """Score operational risk."""
        data = _rk.check_risk_keywords(text).get("operational_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="operational_risk",
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
