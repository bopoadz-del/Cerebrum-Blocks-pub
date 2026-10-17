"""RealEstate Block v2 - TypedBlock implementation

This is the v2 implementation that:
- Extends TypedBlock instead of UniversalContainer
- Accepts TextContent input (from pdf_v2, ocr_v2, etc.)
- Outputs RealEstateAnalysis type
- Has a single process() entry point instead of action routing
- Internal methods are private (_ prefixed)
- Uses deterministic regex + math, no LLM calls, no external APIs
"""

import re
from typing import Any, Dict, List, Optional

from app.core.domain_block_v2 import DomainBlockV2
from app.core.schema_registry import TextContent, RealEstateAnalysis
from app.core.real_estate_types import RiskScore

from app.core.real_estate_knowledge import RealEstateKnowledge, COMPLIANCE_KEYWORDS
from app.core.http_errors import error_kind

_rk = RealEstateKnowledge()


class RealEstateBlockV2(DomainBlockV2):
    """
    RealEstate Block v2 - TypedBlock implementation for real_estate document analysis.

    Input: TextContent (extracted document text)
    Output: RealEstateAnalysis (entities, metrics, compliance flags, risk scores)
    """

    name = "real_estate_v2"
    version = "2.0"
    description = "RealEstate document analysis with typed input/output"
    layer = 3
    tags = ["domain", "real_estate", "v2"]
    requires = []

    default_config = {
        "confidence_threshold": 0.85,
    }

    input_schema = TextContent
    output_schema = RealEstateAnalysis

    accepted_input_types = ["TextContent", "PDFContent"]
    produced_output_types = ["RealEstateAnalysis"]

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste real estate document text...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "cap_rate", "type": "number", "label": "Cap Rate %"},
                {"name": "gross_rent_multiplier", "type": "number", "label": "GRM"},
                {"name": "cash_on_cash_return", "type": "number", "label": "Cash-on-Cash %"},
                {"name": "price_per_sqft", "type": "number", "label": "Price / sqft"},
                {"name": "tenant_risk", "type": "number", "label": "Tenant Risk"},
                {"name": "market_risk", "type": "number", "label": "Market Risk"},
                {"name": "physical_risk", "type": "number", "label": "Physical Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze Lease Agreement", "prompt": "Analyze this lease agreement"},
            {"icon": "🏠", "label": "Check Tenancy Compliance", "prompt": "Check this document for tenancy compliance"},
            {"icon": "⚠️", "label": "Score Property Risks", "prompt": "Score property risks for this document"},
            {"icon": "🔍", "label": "Extract Rent & Terms", "prompt": "Extract rent and terms from this document"},
        ],
    }

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Main entry point - analyze real_estate document text."""
        params = params or {}

        text = self._extract_text(input_data)
        if not text:
            return self._empty_analysis("No text provided")

        custom_rules = params.get("custom_rules") or params.get("rules")
        if custom_rules:
            _rk.set_custom_rules(custom_rules)

        document_type = params.get("document_type") or params.get("analysis_type") or self._detect_document_type(text)

        if document_type == "lease_agreement":
            return await self._analyze_lease_agreement(text, params)
        if document_type == "purchase_contract":
            return await self._analyze_purchase_contract(text, params)
        if document_type == "title_deed":
            return await self._analyze_title_deed(text, params)
        if document_type == "valuation_report":
            return await self._analyze_valuation_report(text, params)
        if document_type == "strata_report":
            return await self._analyze_strata_report(text, params)
        if document_type == "property_inspection":
            return await self._analyze_property_inspection(text, params)
        if document_type == "mortgage_document":
            return await self._analyze_mortgage_document(text, params)
        if document_type == "zoning_permit":
            return await self._analyze_zoning_permit(text, params)

        return await self._analyze_generic(text, params)

    # ------------------------------------------------------------------
    # TEXT EXTRACTION
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DOCUMENT TYPE DETECTION
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        """Auto-detect real_estate document type from content."""
        text_lower = text[:5000].lower()

        if any(kw in text_lower for kw in ['lease', 'lessor', 'lessee', 'rent', 'term', 'security deposit', 'renewal', 'break clause']):
            return "lease_agreement"
        if any(kw in text_lower for kw in ['purchase agreement', 'buyer', 'seller', 'closing date', 'earnest money', 'contingencies']):
            return "purchase_contract"
        if any(kw in text_lower for kw in ['title', 'deed', 'grantor', 'grantee', 'legal description', 'plat', 'parcel', 'lot']):
            return "title_deed"
        if any(kw in text_lower for kw in ['appraisal', 'valuation', 'comparable sales', 'cap rate', 'dcf', 'market value', 'assessed value']):
            return "valuation_report"
        if any(kw in text_lower for kw in ['strata', 'hoa', 'condominium', 'common property', 'special levy', 'sinking fund', 'bylaws']):
            return "strata_report"
        if any(kw in text_lower for kw in ['inspection', 'condition report', 'defects', 'structural', 'pest', 'moisture', 'safety']):
            return "property_inspection"
        if any(kw in text_lower for kw in ['mortgage', 'deed of trust', 'lender', 'borrower', 'principal', 'interest rate', 'amortization']):
            return "mortgage_document"
        if any(kw in text_lower for kw in ['zoning', 'permit', 'land use', 'setback', 'floor area ratio', 'height limit', 'variance']):
            return "zoning_permit"

        return "generic"

    # ------------------------------------------------------------------
    # ANALYSIS METHODS (private)
    # ------------------------------------------------------------------

    async def _analyze_lease_agreement(self, text: str, params: Dict) -> Dict:
        """Analyze lease agreement text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "lease_agreement"
        return self._finalize_result(result, params)

    async def _analyze_purchase_contract(self, text: str, params: Dict) -> Dict:
        """Analyze purchase contract text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "purchase_contract"
        return self._finalize_result(result, params)

    async def _analyze_title_deed(self, text: str, params: Dict) -> Dict:
        """Analyze title deed text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "title_deed"
        return self._finalize_result(result, params)

    async def _analyze_valuation_report(self, text: str, params: Dict) -> Dict:
        """Analyze valuation report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "valuation_report"
        return self._finalize_result(result, params)

    async def _analyze_strata_report(self, text: str, params: Dict) -> Dict:
        """Analyze strata report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "strata_report"
        return self._finalize_result(result, params)

    async def _analyze_property_inspection(self, text: str, params: Dict) -> Dict:
        """Analyze property inspection text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "property_inspection"
        return self._finalize_result(result, params)

    async def _analyze_mortgage_document(self, text: str, params: Dict) -> Dict:
        """Analyze mortgage document text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "mortgage_document"
        return self._finalize_result(result, params)

    async def _analyze_zoning_permit(self, text: str, params: Dict) -> Dict:
        """Analyze zoning permit text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "zoning_permit"
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
            "property_addresses": self._extract_property_addresses(text),
            "parcel_numbers": self._extract_parcel_numbers(text),
            "parties": self._extract_parties(text),
            "rent_amounts": self._extract_rent_amounts(text),
            "lease_terms": self._extract_lease_terms(text),
            "security_deposits": self._extract_security_deposits(text),
            "agents": self._extract_agents(text),
            "tenants": self._extract_tenants(text),
        }
        metrics = {
            "cap_rate": self._extract_cap_rate(**params.get("cap_rate", {})),
            "gross_rent_multiplier": self._extract_gross_rent_multiplier(**params.get("gross_rent_multiplier", {})),
            "cash_on_cash_return": self._extract_cash_on_cash_return(**params.get("cash_on_cash_return", {})),
            "dscr": self._extract_dscr(**params.get("dscr", {})),
            "loan_to_value": self._extract_loan_to_value(**params.get("loan_to_value", {})),
            "net_operating_income": self._extract_net_operating_income(**params.get("net_operating_income", {})),
            "vacancy_rate": self._extract_vacancy_rate(**params.get("vacancy_rate", {})),
            "price_per_sqft": self._extract_price_per_sqft(**params.get("price_per_sqft", {})),
        }
        compliance_flags = {
            "tenancy_law": self._check_tenancy_law(text),
            "aml_property": self._check_aml_property(text),
            "zoning": self._check_zoning(text),
            "strata": self._check_strata(text),
            "disclosure": self._check_disclosure(text),
        }
        risk_scores = {
            "tenant_risk": self._score_tenant_risk(text),
            "market_risk": self._score_market_risk(text),
            "legal_risk": self._score_legal_risk(text),
            "physical_risk": self._score_physical_risk(text),
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
                "property_type": self._extract_property_type(text),
            },
        }

    def _extract_property_type(self, text: str) -> Optional[str]:
        """Best-effort extraction of property type."""
        pattern = r"(?:property type|property_type)[:\s]+([A-Z][A-Za-z0-9\s&.,-]{2,60})"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            return match.group(1).strip()
        return None

    # ------------------------------------------------------------------
    # ENTITY EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_property_addresses(self, text: str) -> List[Dict]:
        """Extract property addresses from text."""
        found = []
        for match in re.finditer(r"(?:property address|address|located at|premises)\s*[\-:]?\s*(\d+\s+[A-Za-z0-9\s.,#\-]+(?:\n|\,|\.))", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "property_addresses",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_parcel_numbers(self, text: str) -> List[Dict]:
        """Extract parcel numbers from text."""
        found = []
        for match in re.finditer(r"(?:parcel|apn|tax lot|folio number)\s*#?\s*(\d{10,20})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "parcel_numbers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_parties(self, text: str) -> List[Dict]:
        """Extract parties from text."""
        found = []
        for match in re.finditer(r"(?:landlord|tenant|buyer|seller|vendor|purchaser|mortgagor|mortgagee)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?|Trust)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "parties",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_rent_amounts(self, text: str) -> List[Dict]:
        """Extract rent amounts from text."""
        found = []
        for match in re.finditer(r"(?:\$)\s*([\d,]+(?:\.\d{1,2})?)\s*(?:per month|monthly|annual rent|base rent|/mo)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "rent_amounts",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_lease_terms(self, text: str) -> List[Dict]:
        """Extract lease terms from text."""
        found = []
        for match in re.finditer(r"(\d+)\s*(month|year|months|years)\s*(?:term|lease term|commencement)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "lease_terms",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_security_deposits(self, text: str) -> List[Dict]:
        """Extract security deposits from text."""
        found = []
        for match in re.finditer(r"(?:security deposit|bond|bank guarantee)\s*[\-:]?\s*(?:\$)?\s*([\d,]+(?:\.\d{1,2})?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "security_deposits",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_agents(self, text: str) -> List[Dict]:
        """Extract agents from text."""
        found = []
        for match in re.finditer(r"(?:real estate agent|broker|property manager|rea|listing agent)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "agents",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_tenants(self, text: str) -> List[Dict]:
        """Extract tenants from text."""
        found = []
        for match in re.finditer(r"(?:tenant|occupant|subtenant|assignee|guarantor)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?|Trust)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "tenants",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    # ------------------------------------------------------------------
    # METRICS & FORMULA EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_cap_rate(self, net_operating_income=None, property_value=None) -> Dict[str, Any]:
        """Calculate cap rate."""
        try:
            value = self._safe_divide(net_operating_income, property_value, scale=100) if (net_operating_income is not None and property_value is not None) else None
            if value is None:
                return {"name": "cap_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "cap_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "cap_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_gross_rent_multiplier(self, property_price=None, gross_annual_rent=None) -> Dict[str, Any]:
        """Calculate gross rent multiplier."""
        try:
            value = self._safe_divide(property_price, gross_annual_rent) if (property_price is not None and gross_annual_rent is not None) else None
            if value is None:
                return {"name": "gross_rent_multiplier", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "gross_rent_multiplier", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "gross_rent_multiplier", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_cash_on_cash_return(self, annual_cash_flow=None, total_cash_invested=None) -> Dict[str, Any]:
        """Calculate cash on cash return."""
        try:
            value = self._safe_divide(annual_cash_flow, total_cash_invested, scale=100) if (annual_cash_flow is not None and total_cash_invested is not None) else None
            if value is None:
                return {"name": "cash_on_cash_return", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "cash_on_cash_return", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "cash_on_cash_return", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_dscr(self, noi=None, debt_service=None) -> Dict[str, Any]:
        """Calculate dscr."""
        try:
            value = self._safe_divide(noi, debt_service) if (noi is not None and debt_service is not None) else None
            if value is None:
                return {"name": "dscr", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "dscr", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "dscr", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_loan_to_value(self, loan_amount=None, property_value=None) -> Dict[str, Any]:
        """Calculate loan to value."""
        try:
            value = self._safe_divide(loan_amount, property_value, scale=100) if (loan_amount is not None and property_value is not None) else None
            if value is None:
                return {"name": "loan_to_value", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "loan_to_value", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "loan_to_value", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_net_operating_income(self, gross_income=None, operating_expenses=None) -> Dict[str, Any]:
        """Calculate net operating income."""
        try:
            value = (gross_income - operating_expenses) if gross_income is not None and operating_expenses is not None else None
            if value is None:
                return {"name": "net_operating_income", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "net_operating_income", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "net_operating_income", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_vacancy_rate(self, vacant_units=None, total_units=None) -> Dict[str, Any]:
        """Calculate vacancy rate."""
        try:
            value = self._safe_divide(vacant_units, total_units, scale=100) if (vacant_units is not None and total_units is not None) else None
            if value is None:
                return {"name": "vacancy_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "vacancy_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "vacancy_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_price_per_sqft(self, price=None, sqft=None) -> Dict[str, Any]:
        """Calculate price per sqft."""
        try:
            value = self._safe_divide(price, sqft) if (price is not None and sqft is not None) else None
            if value is None:
                return {"name": "price_per_sqft", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "price_per_sqft", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "price_per_sqft", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    # ------------------------------------------------------------------
    # REGULATORY & COMPLIANCE CHECKING (private)
    # ------------------------------------------------------------------

    def _check_tenancy_law(self, text: str) -> Dict[str, Any]:
        """Check tenancy law compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["tenancy_law"] if kw in text.lower()]
        return {
            "regulation": "tenancy_law",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_aml_property(self, text: str) -> Dict[str, Any]:
        """Check aml property compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["aml_property"] if kw in text.lower()]
        return {
            "regulation": "aml_property",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_zoning(self, text: str) -> Dict[str, Any]:
        """Check zoning compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["zoning"] if kw in text.lower()]
        return {
            "regulation": "zoning",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_strata(self, text: str) -> Dict[str, Any]:
        """Check strata compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["strata"] if kw in text.lower()]
        return {
            "regulation": "strata",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_disclosure(self, text: str) -> Dict[str, Any]:
        """Check disclosure compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["disclosure"] if kw in text.lower()]
        return {
            "regulation": "disclosure",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    # ------------------------------------------------------------------
    # RISK SCORING (private)
    # ------------------------------------------------------------------

    def _score_tenant_risk(self, text: str) -> RiskScore:
        """Score tenant risk."""
        data = _rk.check_risk_keywords(text).get("tenant_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="tenant_risk",
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

    def _score_legal_risk(self, text: str) -> RiskScore:
        """Score legal risk."""
        data = _rk.check_risk_keywords(text).get("legal_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="legal_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_physical_risk(self, text: str) -> RiskScore:
        """Score physical risk."""
        data = _rk.check_risk_keywords(text).get("physical_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="physical_risk",
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
