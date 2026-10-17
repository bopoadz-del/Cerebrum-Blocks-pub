"""Manufacturing Block v2 - TypedBlock implementation

This is the v2 implementation that:
- Extends TypedBlock instead of UniversalContainer
- Accepts TextContent input (from pdf_v2, ocr_v2, etc.)
- Outputs ManufacturingAnalysis type
- Has a single process() entry point instead of action routing
- Internal methods are private (_ prefixed)
- Uses deterministic regex + math, no LLM calls, no external APIs
"""

import re
from typing import Any, Dict, List, Optional

from app.core.domain_block_v2 import DomainBlockV2
from app.core.schema_registry import TextContent, ManufacturingAnalysis
from app.core.manufacturing_types import RiskScore

from app.core.manufacturing_knowledge import ManufacturingKnowledge, COMPLIANCE_KEYWORDS
from app.core.http_errors import error_kind

_rk = ManufacturingKnowledge()


class ManufacturingBlockV2(DomainBlockV2):
    """
    Manufacturing Block v2 - TypedBlock implementation for manufacturing document analysis.

    Input: TextContent (extracted document text)
    Output: ManufacturingAnalysis (entities, metrics, compliance flags, risk scores)
    """

    name = "manufacturing_v2"
    version = "2.0"
    description = "Manufacturing document analysis with typed input/output"
    layer = 3
    tags = ["domain", "manufacturing", "v2"]
    requires = []

    default_config = {
        "confidence_threshold": 0.85,
    }

    input_schema = TextContent
    output_schema = ManufacturingAnalysis

    accepted_input_types = ["TextContent", "PDFContent"]
    produced_output_types = ["ManufacturingAnalysis"]

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste manufacturing document text...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "oee", "type": "number", "label": "OEE %"},
                {"name": "first_pass_yield", "type": "number", "label": "First Pass Yield %"},
                {"name": "scrap_rate", "type": "number", "label": "Scrap Rate %"},
                {"name": "cost_per_unit", "type": "number", "label": "Cost / Unit"},
                {"name": "quality_risk", "type": "number", "label": "Quality Risk"},
                {"name": "supply_chain_risk", "type": "number", "label": "Supply Chain Risk"},
                {"name": "equipment_risk", "type": "number", "label": "Equipment Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze BOM", "prompt": "Analyze this bill of materials"},
            {"icon": "🏭", "label": "Check ISO 9001 Compliance", "prompt": "Check this document for ISO 9001 compliance"},
            {"icon": "⚠️", "label": "Score Manufacturing Risks", "prompt": "Score manufacturing risks for this document"},
            {"icon": "🔍", "label": "Extract Parts & Defects", "prompt": "Extract parts and defects from this document"},
        ],
    }

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Main entry point - analyze manufacturing document text."""
        params = params or {}

        text = self._extract_text(input_data)
        if not text:
            return self._empty_analysis("No text provided")

        custom_rules = params.get("custom_rules") or params.get("rules")
        if custom_rules:
            _rk.set_custom_rules(custom_rules)

        document_type = params.get("document_type") or params.get("analysis_type") or self._detect_document_type(text)

        if document_type == "bill_of_materials":
            return await self._analyze_bill_of_materials(text, params)
        if document_type == "work_order":
            return await self._analyze_work_order(text, params)
        if document_type == "quality_control_report":
            return await self._analyze_quality_control_report(text, params)
        if document_type == "production_schedule":
            return await self._analyze_production_schedule(text, params)
        if document_type == "supplier_audit":
            return await self._analyze_supplier_audit(text, params)
        if document_type == "equipment_maintenance":
            return await self._analyze_equipment_maintenance(text, params)
        if document_type == "safety_data_sheet":
            return await self._analyze_safety_data_sheet(text, params)
        if document_type == "lean_six_sigma":
            return await self._analyze_lean_six_sigma(text, params)

        return await self._analyze_generic(text, params)

    # ------------------------------------------------------------------
    # TEXT EXTRACTION
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DOCUMENT TYPE DETECTION
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        """Auto-detect manufacturing document type from content."""
        text_lower = text[:5000].lower()

        if any(kw in text_lower for kw in ['bom', 'bill of materials', 'component', 'part number', 'quantity per', 'assembly', 'subassembly']):
            return "bill_of_materials"
        if any(kw in text_lower for kw in ['work order', 'wo', 'routing', 'operation', 'setup time', 'run time', 'machine', 'labor']):
            return "work_order"
        if any(kw in text_lower for kw in ['qc', 'inspection', 'tolerance', 'defect', 'reject', 'pass', 'aql', 'spc', 'control chart']):
            return "quality_control_report"
        if any(kw in text_lower for kw in ['mps', 'production plan', 'capacity', 'throughput', 'cycle time', 'takt time', 'bottleneck']):
            return "production_schedule"
        if any(kw in text_lower for kw in ['supplier audit', 'scorecard', 'iso 9001', 'corrective action', 'scar', 'on-time delivery']):
            return "supplier_audit"
        if any(kw in text_lower for kw in ['pm', 'preventive maintenance', 'mtbf', 'mttr', 'breakdown', 'spare parts', 'calibration']):
            return "equipment_maintenance"
        if any(kw in text_lower for kw in ['sds', 'msds', 'hazard', 'ghs', 'ppe', 'exposure limit', 'flash point', 'first aid']):
            return "safety_data_sheet"
        if any(kw in text_lower for kw in ['kaizen', '5s', 'value stream', 'dmaic', 'waste', 'defect', 'dpmo', 'sigma level']):
            return "lean_six_sigma"

        return "generic"

    # ------------------------------------------------------------------
    # ANALYSIS METHODS (private)
    # ------------------------------------------------------------------

    async def _analyze_bill_of_materials(self, text: str, params: Dict) -> Dict:
        """Analyze bill of materials text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "bill_of_materials"
        return self._finalize_result(result, params)

    async def _analyze_work_order(self, text: str, params: Dict) -> Dict:
        """Analyze work order text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "work_order"
        return self._finalize_result(result, params)

    async def _analyze_quality_control_report(self, text: str, params: Dict) -> Dict:
        """Analyze quality control report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "quality_control_report"
        return self._finalize_result(result, params)

    async def _analyze_production_schedule(self, text: str, params: Dict) -> Dict:
        """Analyze production schedule text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "production_schedule"
        return self._finalize_result(result, params)

    async def _analyze_supplier_audit(self, text: str, params: Dict) -> Dict:
        """Analyze supplier audit text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "supplier_audit"
        return self._finalize_result(result, params)

    async def _analyze_equipment_maintenance(self, text: str, params: Dict) -> Dict:
        """Analyze equipment maintenance text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "equipment_maintenance"
        return self._finalize_result(result, params)

    async def _analyze_safety_data_sheet(self, text: str, params: Dict) -> Dict:
        """Analyze safety data sheet text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "safety_data_sheet"
        return self._finalize_result(result, params)

    async def _analyze_lean_six_sigma(self, text: str, params: Dict) -> Dict:
        """Analyze lean six sigma text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "lean_six_sigma"
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
            "part_numbers": self._extract_part_numbers(text),
            "quantities": self._extract_quantities(text),
            "machines": self._extract_machines(text),
            "operations": self._extract_operations(text),
            "suppliers": self._extract_suppliers(text),
            "defect_codes": self._extract_defect_codes(text),
            "inspection_results": self._extract_inspection_results(text),
            "batch_numbers": self._extract_batch_numbers(text),
        }
        metrics = {
            "oee": self._extract_oee(**params.get("oee", {})),
            "first_pass_yield": self._extract_first_pass_yield(**params.get("first_pass_yield", {})),
            "scrap_rate": self._extract_scrap_rate(**params.get("scrap_rate", {})),
            "rework_rate": self._extract_rework_rate(**params.get("rework_rate", {})),
            "downtime_percentage": self._extract_downtime_percentage(**params.get("downtime_percentage", {})),
            "cycle_time": self._extract_cycle_time(**params.get("cycle_time", {})),
            "takt_time": self._extract_takt_time(**params.get("takt_time", {})),
            "cost_per_unit": self._extract_cost_per_unit(**params.get("cost_per_unit", {})),
        }
        compliance_flags = {
            "iso_9001": self._check_iso_9001(text),
            "iso_14001": self._check_iso_14001(text),
            "osha": self._check_osha(text),
            "reach_rohs": self._check_reach_rohs(text),
            "product_traceability": self._check_product_traceability(text),
        }
        risk_scores = {
            "quality_risk": self._score_quality_risk(text),
            "supply_chain_risk": self._score_supply_chain_risk(text),
            "equipment_risk": self._score_equipment_risk(text),
            "compliance_risk": self._score_compliance_risk(text),
            "cost_risk": self._score_cost_risk(text),
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
                "plant_name": self._extract_plant_name(text),
            },
        }

    def _extract_plant_name(self, text: str) -> Optional[str]:
        """Best-effort extraction of plant name."""
        pattern = r"(?:plant name|plant_name)[:\s]+([A-Z][A-Za-z0-9\s&.,-]{2,60})"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            return match.group(1).strip()
        return None

    # ------------------------------------------------------------------
    # ENTITY EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_part_numbers(self, text: str) -> List[Dict]:
        """Extract part numbers from text."""
        found = []
        for match in re.finditer(r"(?:pn|part number|item number|sku|drawing number)\s*#?\s*([A-Z0-9\-]{6,12})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "part_numbers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_quantities(self, text: str) -> List[Dict]:
        """Extract quantities from text."""
        found = []
        for match in re.finditer(r"(\d+)\s*(ea|units|pcs|kg|lbs|meters|feet|liters)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "quantities",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_machines(self, text: str) -> List[Dict]:
        """Extract machines from text."""
        found = []
        for match in re.finditer(r"(?:machine|equipment|asset|cnc|lathe|mill|press|robot|line)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s\-#]+)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "machines",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_operations(self, text: str) -> List[Dict]:
        """Extract operations from text."""
        found = []
        for match in re.finditer(r"(?:operation|step|process|weld|cut|drill|assemble|paint|test)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s\-]+)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "operations",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_suppliers(self, text: str) -> List[Dict]:
        """Extract suppliers from text."""
        found = []
        for match in re.finditer(r"(?:supplier|vendor|subcontractor|oem|tier 1|tier 2)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "suppliers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_defect_codes(self, text: str) -> List[Dict]:
        """Extract defect codes from text."""
        found = []
        for match in re.finditer(r"(?:defect code|reject code|nc|non-conformance|scrap|rework)\s*[\-:]?\s*([A-Z0-9\-]{3,12})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "defect_codes",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_inspection_results(self, text: str) -> List[Dict]:
        """Extract inspection results from text."""
        found = []
        for match in re.finditer(r"\b(pass|fail|conditional|hold|release|accept|reject)\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "inspection_results",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_batch_numbers(self, text: str) -> List[Dict]:
        """Extract batch numbers from text."""
        found = []
        for match in re.finditer(r"(?:batch|lot|heat number|serial number)\s*#?\s*(\d{6,10})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "batch_numbers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    # ------------------------------------------------------------------
    # METRICS & FORMULA EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_oee(self, availability=None, performance=None, quality=None) -> Dict[str, Any]:
        """Calculate oee."""
        try:
            value = (availability * performance * quality) if (availability is not None and performance is not None and quality is not None) else None
            if value is None:
                return {"name": "oee", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "oee", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "oee", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_first_pass_yield(self, good_units=None, total_units=None) -> Dict[str, Any]:
        """Calculate first pass yield."""
        try:
            value = self._safe_divide(good_units, total_units, scale=100) if (good_units is not None and total_units is not None) else None
            if value is None:
                return {"name": "first_pass_yield", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "first_pass_yield", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "first_pass_yield", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_scrap_rate(self, scrap_units=None, total_units=None) -> Dict[str, Any]:
        """Calculate scrap rate."""
        try:
            value = self._safe_divide(scrap_units, total_units, scale=100) if (scrap_units is not None and total_units is not None) else None
            if value is None:
                return {"name": "scrap_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "scrap_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "scrap_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_rework_rate(self, rework_units=None, total_units=None) -> Dict[str, Any]:
        """Calculate rework rate."""
        try:
            value = self._safe_divide(rework_units, total_units, scale=100) if (rework_units is not None and total_units is not None) else None
            if value is None:
                return {"name": "rework_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "rework_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "rework_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_downtime_percentage(self, downtime_minutes=None, total_minutes=None) -> Dict[str, Any]:
        """Calculate downtime percentage."""
        try:
            value = self._safe_divide(downtime_minutes, total_minutes, scale=100) if (downtime_minutes is not None and total_minutes is not None) else None
            if value is None:
                return {"name": "downtime_percentage", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "downtime_percentage", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "downtime_percentage", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_cycle_time(self, production_time=None, units_produced=None) -> Dict[str, Any]:
        """Calculate cycle time."""
        try:
            value = self._safe_divide(production_time, units_produced) if (production_time is not None and units_produced is not None) else None
            if value is None:
                return {"name": "cycle_time", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "cycle_time", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "cycle_time", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_takt_time(self, available_time=None, customer_demand=None) -> Dict[str, Any]:
        """Calculate takt time."""
        try:
            value = self._safe_divide(available_time, customer_demand) if (available_time is not None and customer_demand is not None) else None
            if value is None:
                return {"name": "takt_time", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "takt_time", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "takt_time", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_cost_per_unit(self, total_cost=None, units_produced=None) -> Dict[str, Any]:
        """Calculate cost per unit."""
        try:
            value = self._safe_divide(total_cost, units_produced) if (total_cost is not None and units_produced is not None) else None
            if value is None:
                return {"name": "cost_per_unit", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "cost_per_unit", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "cost_per_unit", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    # ------------------------------------------------------------------
    # REGULATORY & COMPLIANCE CHECKING (private)
    # ------------------------------------------------------------------

    def _check_iso_9001(self, text: str) -> Dict[str, Any]:
        """Check iso 9001 compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["iso_9001"] if kw in text.lower()]
        return {
            "regulation": "iso_9001",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_iso_14001(self, text: str) -> Dict[str, Any]:
        """Check iso 14001 compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["iso_14001"] if kw in text.lower()]
        return {
            "regulation": "iso_14001",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_osha(self, text: str) -> Dict[str, Any]:
        """Check osha compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["osha"] if kw in text.lower()]
        return {
            "regulation": "osha",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_reach_rohs(self, text: str) -> Dict[str, Any]:
        """Check reach rohs compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["reach_rohs"] if kw in text.lower()]
        return {
            "regulation": "reach_rohs",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_product_traceability(self, text: str) -> Dict[str, Any]:
        """Check product traceability compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["product_traceability"] if kw in text.lower()]
        return {
            "regulation": "product_traceability",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    # ------------------------------------------------------------------
    # RISK SCORING (private)
    # ------------------------------------------------------------------

    def _score_quality_risk(self, text: str) -> RiskScore:
        """Score quality risk."""
        data = _rk.check_risk_keywords(text).get("quality_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="quality_risk",
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

    def _score_equipment_risk(self, text: str) -> RiskScore:
        """Score equipment risk."""
        data = _rk.check_risk_keywords(text).get("equipment_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="equipment_risk",
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
