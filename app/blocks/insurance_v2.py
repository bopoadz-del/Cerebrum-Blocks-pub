"""Insurance Block v2 - TypedBlock implementation

This is the v2 implementation that:
- Extends TypedBlock instead of UniversalContainer
- Accepts TextContent input (from pdf_v2, ocr_v2, etc.)
- Outputs InsuranceAnalysis type
- Has a single process() entry point instead of action routing
- Internal methods are private (_ prefixed)
- Uses deterministic regex + math, no LLM calls, no external APIs
"""

import re
from typing import Any, Dict, List, Optional

from app.core.domain_block_v2 import DomainBlockV2
from app.core.schema_registry import TextContent, InsuranceAnalysis
from app.core.insurance_types import RiskScore

from app.core.insurance_knowledge import InsuranceKnowledge, COMPLIANCE_KEYWORDS
from app.core.http_errors import error_kind

_rk = InsuranceKnowledge()


class InsuranceBlockV2(DomainBlockV2):
    """
    Insurance Block v2 - TypedBlock implementation for insurance document analysis.

    Input: TextContent (extracted document text)
    Output: InsuranceAnalysis (entities, metrics, compliance flags, risk scores)
    """

    name = "insurance_v2"
    version = "2.0"
    description = "Insurance document analysis with typed input/output"
    layer = 3
    tags = ["domain", "insurance", "v2"]
    requires = []

    default_config = {
        "confidence_threshold": 0.85,
    }

    input_schema = TextContent
    output_schema = InsuranceAnalysis

    accepted_input_types = ["TextContent", "PDFContent"]
    produced_output_types = ["InsuranceAnalysis"]

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste insurance document text...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "loss_ratio", "type": "number", "label": "Loss Ratio %"},
                {"name": "combined_ratio", "type": "number", "label": "Combined Ratio %"},
                {"name": "rate_on_line", "type": "number", "label": "Rate on Line %"},
                {"name": "retention_ratio", "type": "number", "label": "Retention Ratio %"},
                {"name": "underwriting_risk", "type": "number", "label": "Underwriting Risk"},
                {"name": "fraud_risk", "type": "number", "label": "Fraud Risk"},
                {"name": "catastrophe_risk", "type": "number", "label": "Catastrophe Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze Policy", "prompt": "Analyze this insurance policy"},
            {"icon": "🏛️", "label": "Check Solvency Compliance", "prompt": "Check this document for solvency compliance"},
            {"icon": "⚠️", "label": "Score Insurance Risks", "prompt": "Score insurance risks for this document"},
            {"icon": "🔍", "label": "Extract Coverage & Limits", "prompt": "Extract coverage and limits from this document"},
        ],
    }

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Main entry point - analyze insurance document text."""
        params = params or {}

        text = self._extract_text(input_data)
        if not text:
            return self._empty_analysis("No text provided")

        custom_rules = params.get("custom_rules") or params.get("rules")
        if custom_rules:
            _rk.set_custom_rules(custom_rules)

        document_type = params.get("document_type") or params.get("analysis_type") or self._detect_document_type(text)

        if document_type == "policy":
            return await self._analyze_policy(text, params)
        if document_type == "claim":
            return await self._analyze_claim(text, params)
        if document_type == "underwriting_report":
            return await self._analyze_underwriting_report(text, params)
        if document_type == "actuarial_report":
            return await self._analyze_actuarial_report(text, params)
        if document_type == "reinsurance_treaty":
            return await self._analyze_reinsurance_treaty(text, params)
        if document_type == "regulatory_filing":
            return await self._analyze_regulatory_filing(text, params)
        if document_type == "binder":
            return await self._analyze_binder(text, params)
        if document_type == "endorsement":
            return await self._analyze_endorsement(text, params)

        return await self._analyze_generic(text, params)

    # ------------------------------------------------------------------
    # TEXT EXTRACTION
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DOCUMENT TYPE DETECTION
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        """Auto-detect insurance document type from content."""
        text_lower = text[:5000].lower()

        if any(kw in text_lower for kw in ['policy', 'coverage', 'premium', 'deductible', 'limit', 'endorsement', 'rider', 'schedule']):
            return "policy"
        if any(kw in text_lower for kw in ['claim', 'loss', 'damage', 'incident date', 'adjuster', 'settlement', 'reserve', 'subrogation']):
            return "claim"
        if any(kw in text_lower for kw in ['underwriting', 'risk assessment', 'exposure', 'hazard', 'classification', 'rate', 'tier']):
            return "underwriting_report"
        if any(kw in text_lower for kw in ['actuarial', 'reserve analysis', 'ibnr', 'loss ratio', 'combined ratio', 'pricing']):
            return "actuarial_report"
        if any(kw in text_lower for kw in ['reinsurance', 'treaty', 'facultative', 'cession', 'retention', 'quota share', 'excess of loss']):
            return "reinsurance_treaty"
        if any(kw in text_lower for kw in ['naic', 'solvency ii', 'orsa', 'statutory', 'annual statement', 'rbc', 'capital adequacy']):
            return "regulatory_filing"
        if any(kw in text_lower for kw in ['binder', 'temporary coverage', 'effective date', 'subjectivities', 'evidence of insurance']):
            return "binder"
        if any(kw in text_lower for kw in ['endorsement', 'amendment', 'change', 'additional insured', 'waiver', 'exclusion added']):
            return "endorsement"

        return "generic"

    # ------------------------------------------------------------------
    # ANALYSIS METHODS (private)
    # ------------------------------------------------------------------

    async def _analyze_policy(self, text: str, params: Dict) -> Dict:
        """Analyze policy text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "policy"
        return self._finalize_result(result, params)

    async def _analyze_claim(self, text: str, params: Dict) -> Dict:
        """Analyze claim text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "claim"
        return self._finalize_result(result, params)

    async def _analyze_underwriting_report(self, text: str, params: Dict) -> Dict:
        """Analyze underwriting report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "underwriting_report"
        return self._finalize_result(result, params)

    async def _analyze_actuarial_report(self, text: str, params: Dict) -> Dict:
        """Analyze actuarial report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "actuarial_report"
        return self._finalize_result(result, params)

    async def _analyze_reinsurance_treaty(self, text: str, params: Dict) -> Dict:
        """Analyze reinsurance treaty text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "reinsurance_treaty"
        return self._finalize_result(result, params)

    async def _analyze_regulatory_filing(self, text: str, params: Dict) -> Dict:
        """Analyze regulatory filing text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "regulatory_filing"
        return self._finalize_result(result, params)

    async def _analyze_binder(self, text: str, params: Dict) -> Dict:
        """Analyze binder text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "binder"
        return self._finalize_result(result, params)

    async def _analyze_endorsement(self, text: str, params: Dict) -> Dict:
        """Analyze endorsement text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "endorsement"
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
            "policy_numbers": self._extract_policy_numbers(text),
            "claim_numbers": self._extract_claim_numbers(text),
            "insured_names": self._extract_insured_names(text),
            "brokers": self._extract_brokers(text),
            "carriers": self._extract_carriers(text),
            "coverage_types": self._extract_coverage_types(text),
            "limits": self._extract_limits(text),
            "deductibles": self._extract_deductibles(text),
        }
        metrics = {
            "loss_ratio": self._extract_loss_ratio(**params.get("loss_ratio", {})),
            "combined_ratio": self._extract_combined_ratio(**params.get("combined_ratio", {})),
            "loss_reserve": self._extract_loss_reserve(**params.get("loss_reserve", {})),
            "ibnr_estimate": self._extract_ibnr_estimate(**params.get("ibnr_estimate", {})),
            "rate_on_line": self._extract_rate_on_line(**params.get("rate_on_line", {})),
            "attachment_point": self._extract_attachment_point(**params.get("attachment_point", {})),
            "retention_ratio": self._extract_retention_ratio(**params.get("retention_ratio", {})),
            "claim_frequency": self._extract_claim_frequency(**params.get("claim_frequency", {})),
        }
        compliance_flags = {
            "solvency_ii": self._check_solvency_ii(text),
            "naic": self._check_naic(text),
            "gdpr": self._check_gdpr(text),
            "anti_money_laundering": self._check_anti_money_laundering(text),
            "claims_handling": self._check_claims_handling(text),
        }
        risk_scores = {
            "underwriting_risk": self._score_underwriting_risk(text),
            "reserve_adequacy": self._score_reserve_adequacy(text),
            "catastrophe_risk": self._score_catastrophe_risk(text),
            "fraud_risk": self._score_fraud_risk(text),
            "litigation_risk": self._score_litigation_risk(text),
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
                "carrier_name": self._extract_carrier_name(text),
            },
        }

    def _extract_carrier_name(self, text: str) -> Optional[str]:
        """Best-effort extraction of carrier name."""
        pattern = r"(?:carrier name|carrier_name)[:\s]+([A-Z][A-Za-z0-9\s&.,-]{2,60})"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            return match.group(1).strip()
        return None

    # ------------------------------------------------------------------
    # ENTITY EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_policy_numbers(self, text: str) -> List[Dict]:
        """Extract policy numbers from text."""
        found = []
        for match in re.finditer(r"(?:policy|policy number)\s*#?\s*(\d{6,12})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "policy_numbers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_claim_numbers(self, text: str) -> List[Dict]:
        """Extract claim numbers from text."""
        found = []
        for match in re.finditer(r"(?:claim|claim number)\s*#?\s*(\d{6,12})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "claim_numbers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_insured_names(self, text: str) -> List[Dict]:
        """Extract insured names from text."""
        found = []
        for match in re.finditer(r"(?:named insured|policyholder|applicant|beneficiary)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "insured_names",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_brokers(self, text: str) -> List[Dict]:
        """Extract brokers from text."""
        found = []
        for match in re.finditer(r"(?:broker|agent|intermediary|mga|mgu)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "brokers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_carriers(self, text: str) -> List[Dict]:
        """Extract carriers from text."""
        found = []
        for match in re.finditer(r"(?:insurer|underwriter|carrier|lloyd's syndicate)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?|Insurance|Re)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "carriers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_coverage_types(self, text: str) -> List[Dict]:
        """Extract coverage types from text."""
        found = []
        for match in re.finditer(r"\b(general liability|property|workers comp|workers' compensation|d&o|e&o|cyber|marine|auto|umbrella|professional liability)\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "coverage_types",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_limits(self, text: str) -> List[Dict]:
        """Extract limits from text."""
        found = []
        for match in re.finditer(r"(?:limit|limits)\s*(?:of\s*)?(?:\$)?\s*([\d,]+(?:\.\d{1,2})?)\s*(?:per occurrence|aggregate|sublimit)?", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "limits",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_deductibles(self, text: str) -> List[Dict]:
        """Extract deductibles from text."""
        found = []
        for match in re.finditer(r"(?:deductible|sir|retention)\s*[\-:]?\s*(?:\$)?\s*([\d,]+(?:\.\d{1,2})?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "deductibles",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    # ------------------------------------------------------------------
    # METRICS & FORMULA EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_loss_ratio(self, incurred_losses=None, earned_premium=None) -> Dict[str, Any]:
        """Calculate loss ratio."""
        try:
            value = self._safe_divide(incurred_losses, earned_premium, scale=100) if (incurred_losses is not None and earned_premium is not None) else None
            if value is None:
                return {"name": "loss_ratio", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "loss_ratio", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "loss_ratio", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_combined_ratio(self, loss_ratio=None, expense_ratio=None) -> Dict[str, Any]:
        """Calculate combined ratio."""
        try:
            value = (loss_ratio + expense_ratio) if (loss_ratio is not None and expense_ratio is not None) else None
            if value is None:
                return {"name": "combined_ratio", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "combined_ratio", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "combined_ratio", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_loss_reserve(self, incurred=None, paid=None) -> Dict[str, Any]:
        """Calculate loss reserve."""
        try:
            value = (incurred - paid) if incurred is not None and paid is not None else None
            if value is None:
                return {"name": "loss_reserve", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "loss_reserve", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "loss_reserve", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_ibnr_estimate(self, total_reserve=None, known_reserve=None) -> Dict[str, Any]:
        """Calculate ibnr estimate."""
        try:
            value = (total_reserve - known_reserve) if total_reserve is not None and known_reserve is not None else None
            if value is None:
                return {"name": "ibnr_estimate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "ibnr_estimate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "ibnr_estimate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_rate_on_line(self, premium=None, limit=None) -> Dict[str, Any]:
        """Calculate rate on line."""
        try:
            value = self._safe_divide(premium, limit, scale=100) if (premium is not None and limit is not None) else None
            if value is None:
                return {"name": "rate_on_line", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "rate_on_line", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "rate_on_line", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_attachment_point(self, excess_limit=None, underlying_limit=None) -> Dict[str, Any]:
        """Calculate attachment point."""
        try:
            value = (excess_limit + underlying_limit) if (excess_limit is not None and underlying_limit is not None) else None
            if value is None:
                return {"name": "attachment_point", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "attachment_point", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "attachment_point", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_retention_ratio(self, ceded_premium=None, gross_premium=None) -> Dict[str, Any]:
        """Calculate retention ratio."""
        try:
            value = self._safe_divide(gross_premium - ceded_premium, gross_premium, scale=100) if (gross_premium is not None and ceded_premium is not None) else None
            if value is None:
                return {"name": "retention_ratio", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "retention_ratio", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "retention_ratio", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_claim_frequency(self, claims=None, exposure_units=None) -> Dict[str, Any]:
        """Calculate claim frequency."""
        try:
            value = self._safe_divide(claims, exposure_units, scale=100) if (claims is not None and exposure_units is not None) else None
            if value is None:
                return {"name": "claim_frequency", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "claim_frequency", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "claim_frequency", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    # ------------------------------------------------------------------
    # REGULATORY & COMPLIANCE CHECKING (private)
    # ------------------------------------------------------------------

    def _check_solvency_ii(self, text: str) -> Dict[str, Any]:
        """Check solvency ii compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["solvency_ii"] if kw in text.lower()]
        return {
            "regulation": "solvency_ii",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_naic(self, text: str) -> Dict[str, Any]:
        """Check naic compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["naic"] if kw in text.lower()]
        return {
            "regulation": "naic",
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

    def _check_anti_money_laundering(self, text: str) -> Dict[str, Any]:
        """Check anti money laundering compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["anti_money_laundering"] if kw in text.lower()]
        return {
            "regulation": "anti_money_laundering",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_claims_handling(self, text: str) -> Dict[str, Any]:
        """Check claims handling compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["claims_handling"] if kw in text.lower()]
        return {
            "regulation": "claims_handling",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    # ------------------------------------------------------------------
    # RISK SCORING (private)
    # ------------------------------------------------------------------

    def _score_underwriting_risk(self, text: str) -> RiskScore:
        """Score underwriting risk."""
        data = _rk.check_risk_keywords(text).get("underwriting_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="underwriting_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_reserve_adequacy(self, text: str) -> RiskScore:
        """Score reserve adequacy."""
        data = _rk.check_risk_keywords(text).get("reserve_adequacy", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="reserve_adequacy",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_catastrophe_risk(self, text: str) -> RiskScore:
        """Score catastrophe risk."""
        data = _rk.check_risk_keywords(text).get("catastrophe_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="catastrophe_risk",
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

    def _score_litigation_risk(self, text: str) -> RiskScore:
        """Score litigation risk."""
        data = _rk.check_risk_keywords(text).get("litigation_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="litigation_risk",
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
