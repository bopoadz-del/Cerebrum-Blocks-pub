"""Pharma Block v2 - TypedBlock implementation

This is the v2 implementation that:
- Extends TypedBlock instead of UniversalContainer
- Accepts TextContent input (from pdf_v2, ocr_v2, etc.)
- Outputs PharmaAnalysis type
- Has a single process() entry point instead of action routing
- Internal methods are private (_ prefixed)
- Uses deterministic regex + math, no LLM calls, no external APIs
"""

import re
from typing import Any, Dict, List, Optional

from app.core.domain_block_v2 import DomainBlockV2
from app.core.schema_registry import TextContent, PharmaAnalysis
from app.core.pharma_types import RiskScore

from app.core.pharma_knowledge import PharmaKnowledge, COMPLIANCE_KEYWORDS
from app.core.http_errors import error_kind

_rk = PharmaKnowledge()


class PharmaBlockV2(DomainBlockV2):
    """
    Pharma Block v2 - TypedBlock implementation for pharma document analysis.

    Input: TextContent (extracted document text)
    Output: PharmaAnalysis (entities, metrics, compliance flags, risk scores)
    """

    name = "pharma_v2"
    version = "2.0"
    description = "Pharma document analysis with typed input/output"
    layer = 3
    tags = ["domain", "pharma", "v2"]
    requires = []

    default_config = {
        "confidence_threshold": 0.85,
    }

    input_schema = TextContent
    output_schema = PharmaAnalysis

    accepted_input_types = ["TextContent", "PDFContent"]
    produced_output_types = ["PharmaAnalysis"]

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste pharmaceutical document text...",
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

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Main entry point - analyze pharma document text."""
        params = params or {}

        text = self._extract_text(input_data)
        if not text:
            return self._empty_analysis("No text provided")

        custom_rules = params.get("custom_rules") or params.get("rules")
        if custom_rules:
            _rk.set_custom_rules(custom_rules)

        document_type = params.get("document_type") or params.get("analysis_type") or self._detect_document_type(text)

        if document_type == "batch_record":
            return await self._analyze_batch_record(text, params)
        if document_type == "clinical_trial_protocol":
            return await self._analyze_clinical_trial_protocol(text, params)
        if document_type == "adverse_event_report":
            return await self._analyze_adverse_event_report(text, params)
        if document_type == "pharmacovigilance":
            return await self._analyze_pharmacovigilance(text, params)
        if document_type == "regulatory_submission":
            return await self._analyze_regulatory_submission(text, params)
        if document_type == "standard_operating_procedure":
            return await self._analyze_standard_operating_procedure(text, params)
        if document_type == "certificate_of_analysis":
            return await self._analyze_certificate_of_analysis(text, params)
        if document_type == "stability_report":
            return await self._analyze_stability_report(text, params)

        return await self._analyze_generic(text, params)

    # ------------------------------------------------------------------
    # TEXT EXTRACTION
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DOCUMENT TYPE DETECTION
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        """Auto-detect pharma document type from content."""
        text_lower = text[:5000].lower()

        if any(kw in text_lower for kw in ['batch', 'lot number', 'manufacturing record', 'bmr', 'yield', 'deviation']):
            return "batch_record"
        if any(kw in text_lower for kw in ['protocol', 'inclusion criteria', 'exclusion criteria', 'primary endpoint', 'cro', 'sponsor']):
            return "clinical_trial_protocol"
        if any(kw in text_lower for kw in ['adverse event', 'sae', 'serious adverse event', 'causality', 'ctcae', 'meddra']):
            return "adverse_event_report"
        if any(kw in text_lower for kw in ['psur', 'pbrer', 'signal detection', 'risk management plan', 'rmp']):
            return "pharmacovigilance"
        if any(kw in text_lower for kw in ['nda', 'bla', 'anda', 'ind', 'cta', 'maa', 'fda', 'ema', 'pmda']):
            return "regulatory_submission"
        if any(kw in text_lower for kw in ['sop', 'procedure', 'work instruction', 'validation', 'calibration']):
            return "standard_operating_procedure"
        if any(kw in text_lower for kw in ['coa', 'assay', 'purity', 'impurity', 'dissolution', 'specification', 'usp', 'ep']):
            return "certificate_of_analysis"
        if any(kw in text_lower for kw in ['stability', 'ich q1a', 'accelerated', 'long term', 'degradation', 'shelf life']):
            return "stability_report"

        return "generic"

    # ------------------------------------------------------------------
    # ANALYSIS METHODS (private)
    # ------------------------------------------------------------------

    async def _analyze_batch_record(self, text: str, params: Dict) -> Dict:
        """Analyze batch record text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "batch_record"
        return self._finalize_result(result, params)

    async def _analyze_clinical_trial_protocol(self, text: str, params: Dict) -> Dict:
        """Analyze clinical trial protocol text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "clinical_trial_protocol"
        return self._finalize_result(result, params)

    async def _analyze_adverse_event_report(self, text: str, params: Dict) -> Dict:
        """Analyze adverse event report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "adverse_event_report"
        return self._finalize_result(result, params)

    async def _analyze_pharmacovigilance(self, text: str, params: Dict) -> Dict:
        """Analyze pharmacovigilance text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "pharmacovigilance"
        return self._finalize_result(result, params)

    async def _analyze_regulatory_submission(self, text: str, params: Dict) -> Dict:
        """Analyze regulatory submission text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "regulatory_submission"
        return self._finalize_result(result, params)

    async def _analyze_standard_operating_procedure(self, text: str, params: Dict) -> Dict:
        """Analyze standard operating procedure text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "standard_operating_procedure"
        return self._finalize_result(result, params)

    async def _analyze_certificate_of_analysis(self, text: str, params: Dict) -> Dict:
        """Analyze certificate of analysis text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "certificate_of_analysis"
        return self._finalize_result(result, params)

    async def _analyze_stability_report(self, text: str, params: Dict) -> Dict:
        """Analyze stability report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "stability_report"
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
            "batch_numbers": self._extract_batch_numbers(text),
            "ndc_numbers": self._extract_ndc_numbers(text),
            "drug_names": self._extract_drug_names(text),
            "dosage_forms": self._extract_dosage_forms(text),
            "strengths": self._extract_strengths(text),
            "expiry_dates": self._extract_expiry_dates(text),
            "manufacturers": self._extract_manufacturers(text),
            "regulatory_refs": self._extract_regulatory_refs(text),
        }
        metrics = {
            "batch_yield": self._extract_batch_yield(**params.get("batch_yield", {})),
            "assay_purity": self._extract_assay_purity(**params.get("assay_purity", {})),
            "impurity_profile": self._extract_impurity_profile(**params.get("impurity_profile", {})),
            "dissolution_rate": self._extract_dissolution_rate(**params.get("dissolution_rate", {})),
            "content_uniformity": self._extract_content_uniformity(**params.get("content_uniformity", {})),
            "stability_degradation": self._extract_stability_degradation(**params.get("stability_degradation", {})),
            "shelf_life": self._extract_shelf_life(**params.get("shelf_life", {})),
            "signal_strength": self._extract_signal_strength(**params.get("signal_strength", {})),
        }
        compliance_flags = {
            "gmp": self._check_gmp(text),
            "fda_21_cfr_11": self._check_fda_21_cfr_11(text),
            "ich_guidelines": self._check_ich_guidelines(text),
            "gdpr": self._check_gdpr(text),
            "serialisation": self._check_serialisation(text),
        }
        risk_scores = {
            "batch_failure": self._score_batch_failure(text),
            "regulatory_action": self._score_regulatory_action(text),
            "supply_chain": self._score_supply_chain(text),
            "patient_safety": self._score_patient_safety(text),
            "ip_risk": self._score_ip_risk(text),
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
                "product_name": self._extract_product_name(text),
            },
        }

    def _extract_product_name(self, text: str) -> Optional[str]:
        """Best-effort extraction of product name."""
        pattern = r"(?:product name|product_name)[:\s]+([A-Z][A-Za-z0-9\s&.,-]{2,60})"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            return match.group(1).strip()
        return None

    # ------------------------------------------------------------------
    # ENTITY EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_batch_numbers(self, text: str) -> List[Dict]:
        """Extract batch numbers from text."""
        found = []
        for match in re.finditer(r"(?:batch|lot)\s*#?\s*(\d{6,10})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "batch_numbers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_ndc_numbers(self, text: str) -> List[Dict]:
        """Extract ndc numbers from text."""
        found = []
        for match in re.finditer(r"\b(\d{4,5}-\d{3,4}-\d{1,2})\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "ndc_numbers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_drug_names(self, text: str) -> List[Dict]:
        """Extract drug names from text."""
        found = []
        for match in re.finditer(r"(?:drug substance|active substance|inn|generic name|brand name)\s*[\-:]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "drug_names",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_dosage_forms(self, text: str) -> List[Dict]:
        """Extract dosage forms from text."""
        found = []
        for match in re.finditer(r"\b(tablet|capsule|injection|syrup|cream|patch|inhaler|ointment|suspension|solution)\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "dosage_forms",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_strengths(self, text: str) -> List[Dict]:
        """Extract strengths from text."""
        found = []
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|IU|%)\s*(?:per unit|each|/unit)?", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "strengths",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_expiry_dates(self, text: str) -> List[Dict]:
        """Extract expiry dates from text."""
        found = []
        for match in re.finditer(r"(?:exp|use by|expiration(?: date)?)\s*[\-:]?\s*(\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "expiry_dates",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_manufacturers(self, text: str) -> List[Dict]:
        """Extract manufacturers from text."""
        found = []
        for match in re.finditer(r"(?:manufactured by|made by|cmo|cdmo)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?|Limited)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "manufacturers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_regulatory_refs(self, text: str) -> List[Dict]:
        """Extract regulatory refs from text."""
        found = []
        for match in re.finditer(r"\b(FDA|EMA|ICH Q\d+[A-Z]?|USP|EP|JP|GMP|GLP|GCP|21 CFR Part 11)\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "regulatory_refs",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    # ------------------------------------------------------------------
    # METRICS & FORMULA EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_batch_yield(self, theoretical_yield=None, actual_yield=None) -> Dict[str, Any]:
        """Calculate batch yield."""
        try:
            value = self._safe_divide(actual_yield, theoretical_yield, scale=100) if (actual_yield is not None and theoretical_yield is not None) else None
            if value is None:
                return {"name": "batch_yield", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "batch_yield", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "batch_yield", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_assay_purity(self, assay_result=None, specification=None) -> Dict[str, Any]:
        """Calculate assay purity."""
        try:
            value = self._safe_divide(assay_result - specification, specification, scale=100) if (assay_result is not None and specification is not None) else None
            if value is None:
                return {"name": "assay_purity", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "assay_purity", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "assay_purity", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_impurity_profile(self, total_impurities=None, individual_impurities=None) -> Dict[str, Any]:
        """Calculate impurity profile."""
        try:
            value = total_impurities if total_impurities is not None else None
            if value is None:
                return {"name": "impurity_profile", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "impurity_profile", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "impurity_profile", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_dissolution_rate(self, dissolved=None, total=None) -> Dict[str, Any]:
        """Calculate dissolution rate."""
        try:
            value = self._safe_divide(dissolved, total, scale=100) if (dissolved is not None and total is not None) else None
            if value is None:
                return {"name": "dissolution_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "dissolution_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "dissolution_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_content_uniformity(self, mean=None, individual_values=None) -> Dict[str, Any]:
        """Calculate content uniformity."""
        try:
            value = mean if mean is not None else None
            if value is None:
                return {"name": "content_uniformity", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "content_uniformity", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "content_uniformity", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_stability_degradation(self, initial_assay=None, final_assay=None, time_months=None) -> Dict[str, Any]:
        """Calculate stability degradation."""
        try:
            value = self._safe_divide(initial_assay - final_assay, time_months) if (initial_assay is not None and final_assay is not None and time_months is not None) else None
            if value is None:
                return {"name": "stability_degradation", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "stability_degradation", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "stability_degradation", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_shelf_life(self, degradation_rate=None, specification_limit=None) -> Dict[str, Any]:
        """Calculate shelf life."""
        try:
            value = self._safe_divide(specification_limit, degradation_rate) if (specification_limit is not None and degradation_rate is not None) else None
            if value is None:
                return {"name": "shelf_life", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "shelf_life", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "shelf_life", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_signal_strength(self, report_count=None, background_rate=None) -> Dict[str, Any]:
        """Calculate signal strength."""
        try:
            value = self._safe_divide(report_count, background_rate) if (report_count is not None and background_rate is not None) else None
            if value is None:
                return {"name": "signal_strength", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "signal_strength", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "signal_strength", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    # ------------------------------------------------------------------
    # REGULATORY & COMPLIANCE CHECKING (private)
    # ------------------------------------------------------------------

    def _check_gmp(self, text: str) -> Dict[str, Any]:
        """Check gmp compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["gmp"] if kw in text.lower()]
        return {
            "regulation": "gmp",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_fda_21_cfr_11(self, text: str) -> Dict[str, Any]:
        """Check fda 21 cfr 11 compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["fda_21_cfr_11"] if kw in text.lower()]
        return {
            "regulation": "fda_21_cfr_11",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_ich_guidelines(self, text: str) -> Dict[str, Any]:
        """Check ich guidelines compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["ich_guidelines"] if kw in text.lower()]
        return {
            "regulation": "ich_guidelines",
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

    def _check_serialisation(self, text: str) -> Dict[str, Any]:
        """Check serialisation compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["serialisation"] if kw in text.lower()]
        return {
            "regulation": "serialisation",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    # ------------------------------------------------------------------
    # RISK SCORING (private)
    # ------------------------------------------------------------------

    def _score_batch_failure(self, text: str) -> RiskScore:
        """Score batch failure."""
        data = _rk.check_risk_keywords(text).get("batch_failure", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="batch_failure",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_regulatory_action(self, text: str) -> RiskScore:
        """Score regulatory action."""
        data = _rk.check_risk_keywords(text).get("regulatory_action", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="regulatory_action",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_supply_chain(self, text: str) -> RiskScore:
        """Score supply chain."""
        data = _rk.check_risk_keywords(text).get("supply_chain", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="supply_chain",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_patient_safety(self, text: str) -> RiskScore:
        """Score patient safety."""
        data = _rk.check_risk_keywords(text).get("patient_safety", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="patient_safety",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_ip_risk(self, text: str) -> RiskScore:
        """Score ip risk."""
        data = _rk.check_risk_keywords(text).get("ip_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="ip_risk",
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
