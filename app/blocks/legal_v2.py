"""Legal Block v2 - TypedBlock implementation

This is the v2 implementation that:
- Extends TypedBlock instead of UniversalContainer
- Accepts TextContent input (from pdf_v2, ocr_v2, etc.)
- Outputs LegalAnalysis type
- Has a single process() entry point instead of action routing
- Internal methods are private (_ prefixed)
- Uses deterministic regex + math, no LLM calls, no external APIs
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.domain_block_v2 import DomainBlockV2
from app.core.schema_registry import TextContent, LegalAnalysis

from app.core.legal_knowledge import LegalKnowledge

_lk = LegalKnowledge()


class LegalBlockV2(DomainBlockV2):
    """
    Legal Block v2 - TypedBlock implementation for legal document analysis.

    Input: TextContent (extracted document text)
    Output: LegalAnalysis (entities, legal analysis, compliance flags, risk scores)
    """

    name = "legal_v2"
    version = "2.0"
    description = "Legal document analysis with typed input/output"
    layer = 3
    tags = ["domain", "legal", "law", "v2"]
    requires = []

    default_config = {
        "confidence_threshold": 0.85,
    }

    # Input: TextContent from pdf_v2, ocr_v2, etc.
    input_schema = TextContent

    # Output: LegalAnalysis
    output_schema = LegalAnalysis

    # Type declarations for orchestrator
    accepted_input_types = ["TextContent", "PDFContent"]
    produced_output_types = ["LegalAnalysis"]

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste legal document text...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "contract_value", "type": "number", "label": "Contract Value"},
                {"name": "limitation_periods", "type": "number", "label": "Limitation Periods"},
                {"name": "termination_provisions", "type": "number", "label": "Termination Provisions"},
                {"name": "litigation_risk", "type": "number", "label": "Litigation Risk"},
                {"name": "regulatory_risk", "type": "number", "label": "Regulatory Risk"},
                {"name": "financial_risk", "type": "number", "label": "Financial Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze Contract", "prompt": "Analyze this legal contract"},
            {"icon": "⚖️", "label": "Check Compliance", "prompt": "Check this document for regulatory compliance"},
            {"icon": "⚠️", "label": "Score Legal Risks", "prompt": "Score legal risks for this document"},
            {"icon": "🔍", "label": "Extract Parties & Counsel", "prompt": "Extract parties, counsel, courts, and citations from this document"},
        ],
    }

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """
        Main entry point - analyze legal document text.

        Input: TextContent dict (or string for backward compatibility)
        Output: LegalAnalysis dict
        """
        params = params or {}

        # Extract text from TextContent format (or plain string)
        text = self._extract_text(input_data)
        if not text:
            return self._empty_analysis("No text provided")

        # Load any user-supplied custom rules
        custom_rules = params.get("custom_rules") or params.get("rules")
        # Per-request knowledge instance: custom rules must never leak
        # across requests through a shared module singleton.
        knowledge = LegalKnowledge()
        if custom_rules:
            knowledge.set_custom_rules(custom_rules)
        # Per-request slot: fresh instance every process() call, so a
        # reused block instance never leaks one request's rules into the
        # next (the old module-level singleton did).
        self._request_knowledge = knowledge

        # Determine analysis type from params or auto-detect
        document_type = params.get("document_type") or params.get("analysis_type") or self._detect_document_type(text)

        # Run analysis based on type
        if document_type == "contract":
            return await self._analyze_contract(text, params)
        elif document_type == "pleading":
            return await self._analyze_pleading(text, params)
        elif document_type == "discovery":
            return await self._analyze_discovery(text, params)
        elif document_type == "opinion":
            return await self._analyze_opinion(text, params)
        elif document_type == "regulation":
            return await self._analyze_regulation(text, params)
        elif document_type == "patent":
            return await self._analyze_patent(text, params)
        elif document_type == "due_diligence":
            return await self._analyze_due_diligence(text, params)
        elif document_type == "settlement":
            return await self._analyze_settlement(text, params)
        else:
            return await self._analyze_generic(text, params)

    # ------------------------------------------------------------------
    # TEXT EXTRACTION
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DOCUMENT TYPE DETECTION
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        """Auto-detect legal document type from content.

        Specific document titles are checked before broad keyword categories.
        """
        text_lower = text[:5000].lower()

        # Settlement — checked early because release/confidentiality terms appear broadly
        if any(kw in text_lower for kw in ["settlement", "mutual release", "covenant not to sue", "release and discharge"]):
            return "settlement"

        # Patent
        if any(kw in text_lower for kw in ["patent", "prior art", "invention", "specification", "uspto", "wipo", "ipc", "cpc"]):
            return "patent"

        # Pleading
        if any(kw in text_lower for kw in ["complaint", "petition", "motion", "brief", "plaintiff", "defendant", "jurisdiction", "relief sought"]):
            return "pleading"

        # Discovery
        if any(kw in text_lower for kw in ["interrogatory", "request for production", "deposition", "subpoena", "rfp", "discovery request", "privilege"]):
            return "discovery"

        # Opinion
        if any(kw in text_lower for kw in ["court opinion", "holding", "precedent", "dicta", "affirmed", "reversed", "remanded", "judge", "justice"]):
            return "opinion"

        # Regulation
        if any(kw in text_lower for kw in ["regulation", "statute", "code", "cfr", "usc", "administrative", "agency rule", "enforcement"]):
            return "regulation"

        # Contract — checked before due_diligence so "Agreement" titles win over DD terms
        if any(kw in text_lower for kw in ["agreement", "whereas", "hereby", "this contract", "terms and conditions"]):
            return "contract"

        # Due diligence
        if any(kw in text_lower for kw in ["due diligence", "representation", "warranty", "indemnification", "escrow", "material adverse change", "mac"]):
            return "due_diligence"

        # Fallback contract indicators
        if any(kw in text_lower for kw in ["party", "terms", "consideration", "breach", "termination", "clause"]):
            return "contract"

        return "generic"

    # ------------------------------------------------------------------
    # ANALYSIS METHODS (private)
    # ------------------------------------------------------------------

    async def _analyze_contract(self, text: str, params: Dict) -> Dict:
        """Analyze contract text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "contract"
        return self._finalize_result(result, params)

    async def _analyze_pleading(self, text: str, params: Dict) -> Dict:
        """Analyze pleading text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "pleading"
        return self._finalize_result(result, params)

    async def _analyze_discovery(self, text: str, params: Dict) -> Dict:
        """Analyze discovery document text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "discovery"
        return self._finalize_result(result, params)

    async def _analyze_opinion(self, text: str, params: Dict) -> Dict:
        """Analyze court opinion text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "opinion"
        return self._finalize_result(result, params)

    async def _analyze_regulation(self, text: str, params: Dict) -> Dict:
        """Analyze regulation text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "regulation"
        return self._finalize_result(result, params)

    async def _analyze_patent(self, text: str, params: Dict) -> Dict:
        """Analyze patent document text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "patent"
        return self._finalize_result(result, params)

    async def _analyze_due_diligence(self, text: str, params: Dict) -> Dict:
        """Analyze due diligence document text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "due_diligence"
        return self._finalize_result(result, params)

    async def _analyze_settlement(self, text: str, params: Dict) -> Dict:
        """Analyze settlement document text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "settlement"
        return self._finalize_result(result, params)

    async def _analyze_generic(self, text: str, params: Dict) -> Dict:
        """Generic analysis for unknown legal document types."""
        result = self._build_analysis(text, params)
        result["document_type"] = "generic"
        return self._finalize_result(result, params)

    # ------------------------------------------------------------------
    # BUILDERS
    # ------------------------------------------------------------------

    def _build_analysis(self, text: str, params: Dict) -> Dict:
        """Run all extraction passes and return a working dict."""
        entities = {
            "parties": self._extract_parties(text),
            "counsel": self._extract_counsel(text),
            "courts": self._extract_courts(text),
            "case_numbers": self._extract_case_numbers(text),
            "citations": self._extract_citations(text),
            "statutes": self._extract_statute_references(text),
            "dates": self._extract_dates(text),
            "monetary_values": self._extract_monetary_values(text),
        }
        legal_analysis = {
            "contract_value": self._extract_contract_value(text),
            "liquidated_damages": self._extract_liquidated_damages(text),
            "limitation_periods": self._extract_limitation_periods(text),
            "termination_provisions": self._extract_termination_provisions(text),
            "indemnification_scope": self._extract_indemnification_scope(text),
            "governing_law": self._extract_governing_law(text),
            "ip_ownership": self._extract_ip_ownership(text),
        }
        compliance_flags = {
            "gdpr": self._check_gdpr(text),
            "ccpa": self._check_ccpa(text),
            "anti_bribery": self._check_anti_bribery(text),
            "antitrust": self._check_antitrust(text),
            "sanctions": self._check_sanctions(text),
            "securities": self._check_securities(text),
        }
        risk_scores = {
            "litigation_risk": self._score_litigation_risk(text),
            "regulatory_risk": self._score_regulatory_risk(text),
            "reputational_risk": self._score_reputational_risk(text),
            "financial_risk": self._score_financial_risk(text),
            "ip_risk": self._score_ip_risk(text),
            "overall_risk": self._compute_overall_risk(text),
        }
        custom_rule_hits = self._request_knowledge.check_custom_rules(text)
        jurisdiction = self._extract_jurisdiction(text)

        return {
            "document_type": "unknown",
            "entities": entities,
            "legal_analysis": legal_analysis,
            "compliance_flags": compliance_flags,
            "risk_scores": risk_scores,
            "custom_rule_hits": custom_rule_hits,
            "text": text,
            "raw_text": text[:2000] if params.get("include_raw") else "",
            "metadata": {
                "extracted_at": self._timestamp(),
                "entity_count": sum(len(v) for v in entities.values()),
                "analysis_count": sum(1 for v in legal_analysis.values() if v and v.get("value") not in (None, [], "")),
                "jurisdiction": jurisdiction,
            },
        }

    # ------------------------------------------------------------------
    # ENTITY EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_parties(self, text: str) -> List[Dict]:
        """Extract legal parties."""
        found = []

        # "Between X and Y" pattern for formal entities (requires a corporate suffix)
        between_pattern = r"(?:between|by and between)\s+([A-Z][A-Za-z0-9\s&\.,]*?(?:Inc\.?|LLC|Ltd\.?|Corp\.?|Corporation|Company|LP|LLP|GmbH|PLC))\s*(?:\([^)]+\))?\s+and\s+([A-Z][A-Za-z0-9\s&\.,]*?(?:Inc\.?|LLC|Ltd\.?|Corp\.?|Corporation|Company|LP|LLP|GmbH|PLC))"
        for match in re.finditer(between_pattern, text, re.IGNORECASE):
            for group_idx in (1, 2):
                name = match.group(group_idx).strip()
                if len(name) > 2:
                    found.append({
                        "type": "party",
                        "value": name,
                        "confidence": 0.9,
                        "context": text[max(0, match.start() - 20):match.end() + 20],
                    })

        # Party labels (value must start with uppercase even with IGNORECASE)
        party_pattern = r"(?:Party|Plaintiff|Defendant|Petitioner|Respondent)\s*[:\s]\s*((?-i:[A-Z])[A-Za-z0-9\s&\.,]*?(?:Inc\.?|LLC|Ltd\.?|Corp\.?|Corporation|Company|LP|LLP|GmbH|PLC)?)(?=\s*[\(\n,;]|$)"
        for match in re.finditer(party_pattern, text, re.IGNORECASE):
            name = match.group(1).strip()
            if len(name) > 2:
                found.append({
                    "type": "party",
                    "value": name,
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })

        return self._deduplicate_entities(found)

    def _extract_counsel(self, text: str) -> List[Dict]:
        """Extract counsel / law firm names."""
        found = []

        # Esq. and law firm patterns
        counsel_pattern = r"(?:Counsel for|Attorney for|represented by)\s+([A-Z][A-Za-z0-9\s&\.,]+(?:Esq\.?|LLP|PC|PLLC|Law Firm|Law Offices|Attorneys|Counsel))?"
        for match in re.finditer(counsel_pattern, text, re.IGNORECASE):
            if match.group(1):
                found.append({
                    "type": "counsel",
                    "value": match.group(1).strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })

        # Name + Esq.
        esq_pattern = r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*,?\s+Esq\.?"
        for match in re.finditer(esq_pattern, text):
            found.append({
                "type": "counsel",
                "value": match.group(0),
                "confidence": 0.8,
                "context": text[max(0, match.start() - 20):match.end() + 20],
            })

        # Law firms ending in LLP/PC
        firm_pattern = r"\b([A-Z][A-Za-z0-9\s&\.,]+(?:LLP|PC|PLLC|Law Group|Law Firm))\b"
        for match in re.finditer(firm_pattern, text):
            found.append({
                "type": "law_firm",
                "value": match.group(1).strip(),
                "confidence": 0.8,
                "context": text[max(0, match.start() - 20):match.end() + 20],
            })

        return self._deduplicate_entities(found)

    def _extract_courts(self, text: str) -> List[Dict]:
        """Extract court and tribunal names."""
        found = []
        court_pattern = r"\b((?:United States|U\.S\.|Federal|State of [A-Z][a-z]+)?\s*(?:District Court|Circuit Court|Court of Appeals|Supreme Court|Bankruptcy Court|Court of [A-Za-z]+|Arbitration Panel|ICC|JAMS|AAA))\b"
        for match in re.finditer(court_pattern, text, re.IGNORECASE):
            name = match.group(1).strip()
            if len(name) > 3:
                found.append({
                    "type": "court",
                    "value": name,
                    "confidence": 0.9,
                    "context": text[max(0, match.start() - 30):match.end() + 30],
                })
        return found

    def _extract_case_numbers(self, text: str) -> List[Dict]:
        """Extract case/docket numbers."""
        patterns = [
            r"\b\d{1,2}:\d{2}-[Cc][Vv]-\d{4,5}\b",
            r"\b(?:No\.?|Case No\.?|Docket)\s*:?\s*\d+[-\w]*\b",
        ]
        found = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                found.append({
                    "type": "case_number",
                    "value": match.group(0),
                    "confidence": 0.9,
                    "context": text[max(0, match.start() - 30):match.end() + 30],
                })
        return found

    def _extract_citations(self, text: str) -> List[Dict]:
        """Extract legal citations."""
        patterns = [
            r"\b\d+\s+U\.S\.\s+\d+\b",
            r"\b\d+\s+F\.\d+d\s+\d+\b",
            r"\b\d+\s+F\.\d+th\s+\d+\b",
            r"\b\d+\s+So\.\d+d\s+\d+\b",
            r"\b\d+\s+N\.E\.\d+d\s+\d+\b",
            r"\b\d+\s+Cal\.\d+d\s+\d+\b",
        ]
        found = []
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                found.append({
                    "type": "citation",
                    "value": match.group(0),
                    "confidence": 0.95,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return found

    def _extract_statute_references(self, text: str) -> List[Dict]:
        """Extract statute and code references."""
        patterns = [
            r"\b\d+\s+U\.S\.C\.\s+§\s*\d+[\w\-\.]*\b",
            r"\b\d+\s+C\.F\.R\.\s+§\s*\d+[\w\-\.]*\b",
            r"\b\d+\s+[A-Z][a-zA-Z]+\s+Code\s+(?:Ann\.?)?\s+§\s*\d+[\w\-\.]*\b",
        ]
        found = []
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                found.append({
                    "type": "statute",
                    "value": match.group(0),
                    "confidence": 0.95,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return found

    def _extract_dates(self, text: str) -> List[Dict]:
        """Extract important legal dates."""
        labels = ["effective date", "execution date", "filing date", "hearing date", "deadline", "statute of limitations", "as of"]
        found = []
        for label in labels:
            pattern = rf"(?:{re.escape(label)})[:\s]+(\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}|\d{{4}}-\d{{1,2}}-\d{{1,2}}|(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{{1,2}},?\s+\d{{4}})"
            for match in re.finditer(pattern, text, re.IGNORECASE):
                found.append({
                    "type": label.replace(" ", "_"),
                    "value": match.group(1),
                    "confidence": 0.9,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return found

    def _extract_monetary_values(self, text: str) -> List[Dict]:
        """Extract monetary amounts (damages, fees, settlement, etc.)."""
        pattern = r"[\$€£¥]\s*([\d,]+(?:\.\d{1,2})?)\s*(million|billion|thousand|m|bn|b|k)?"
        found = []
        for match in re.finditer(pattern, text):
            amount_str = match.group(1).replace(",", "")
            try:
                amount = float(amount_str)
            except ValueError:
                continue
            multiplier = match.group(2)
            if multiplier:
                mlower = multiplier.lower()
                if mlower in {"million", "m"}:
                    amount *= 1_000_000
                elif mlower in {"billion", "bn", "b"}:
                    amount *= 1_000_000_000
                elif mlower in {"thousand", "k"}:
                    amount *= 1_000
            # Determine context
            ctx = text[max(0, match.start() - 60):match.end() + 60].lower()
            category = "amount"
            if any(kw in ctx for kw in ["settlement", "settle"]):
                category = "settlement"
            elif any(kw in ctx for kw in ["damages", "compensatory", "punitive"]):
                category = "damages"
            elif any(kw in ctx for kw in ["fee", "fees", "attorney", "costs"]):
                category = "fees"
            elif any(kw in ctx for kw in ["penalty", "fine"]):
                category = "penalty"
            elif any(kw in ctx for kw in ["contract value", "total value", "annual value"]):
                category = "contract_value"

            found.append({
                "type": category,
                "value": round(amount, 2),
                "raw": match.group(0),
                "confidence": 0.85,
                "context": text[max(0, match.start() - 40):match.end() + 40],
            })
        return found

    # ------------------------------------------------------------------
    # LEGAL ANALYSIS & CALCULATIONS (private)
    # ------------------------------------------------------------------

    def _extract_contract_value(self, text: str) -> Dict[str, Any]:
        """Extract total contract value from text."""
        pattern = r"(?:total contract value|total value|contract sum|annual value|license fee)[:\s]+[\$€£¥]?\s*([\d,]+(?:\.\d{1,2})?)\s*(million|billion|thousand|m|bn|b|k)?"
        values = []
        for match in re.finditer(pattern, text, re.IGNORECASE):
            amount = float(match.group(1).replace(",", ""))
            multiplier = match.group(2)
            if multiplier:
                mlower = multiplier.lower()
                if mlower in {"million", "m"}:
                    amount *= 1_000_000
                elif mlower in {"billion", "bn", "b"}:
                    amount *= 1_000_000_000
                elif mlower in {"thousand", "k"}:
                    amount *= 1_000
            values.append(amount)
        if values:
            return {"name": "contract_value", "value": max(values), "inputs": {"values_found": values}, "confidence": 0.9}
        return {"name": "contract_value", "value": None, "inputs": {}, "error": "No contract value found"}

    def _extract_liquidated_damages(self, text: str) -> Dict[str, Any]:
        """Detect liquidated damages / penalty clauses."""
        text_lower = text.lower()
        indicators = ["liquidated damages", "ld", "penalty", "late fee", "per day", "per diem"]
        found = [kw for kw in indicators if kw in text_lower]
        clauses = []
        for kw in ["liquidated damages", "penalty"]:
            for match in re.finditer(rf"{kw}[\s\w]{{0,100}}\$?\s*[\d,]+", text, re.IGNORECASE):
                clauses.append(match.group(0)[:200])
        return {
            "name": "liquidated_damages",
            "value": bool(found),
            "inputs": {"indicators": found, "clauses": clauses[:3]},
            "confidence": 0.8 if found else 0.0,
        }

    def _extract_limitation_periods(self, text: str) -> Dict[str, Any]:
        """Extract statute of limitations / notice periods."""
        found = []
        pattern = r"(?:statute of limitations|limitation period|claim period|notice period|cure period)[:\s]+(\d+)\s*(day|days|month|months|year|years)"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            found.append({"value": int(match.group(1)), "unit": match.group(2), "raw": match.group(0)})
        return {"name": "limitation_periods", "value": found, "inputs": {}, "confidence": 0.85 if found else 0.0}

    def _extract_termination_provisions(self, text: str) -> Dict[str, Any]:
        """Detect termination provisions."""
        text_lower = text.lower()
        indicators = []
        if "terminate for cause" in text_lower or "termination for cause" in text_lower:
            indicators.append("for_cause")
        if "terminate for convenience" in text_lower or "termination for convenience" in text_lower:
            indicators.append("for_convenience")
        if "termination fee" in text_lower or "early termination fee" in text_lower:
            indicators.append("termination_fee")
        # Notice period
        notice_match = re.search(r"(\d+)\s*(day|days|month|months)\s*(?:written\s+)?notice", text_lower)
        notice_period = None
        if notice_match:
            notice_period = {"value": int(notice_match.group(1)), "unit": notice_match.group(2)}
        return {
            "name": "termination_provisions",
            "value": len(indicators),
            "inputs": {"indicators": indicators, "notice_period": notice_period},
            "confidence": 0.8 if indicators else 0.0,
        }

    def _extract_indemnification_scope(self, text: str) -> Dict[str, Any]:
        """Detect indemnification scope and caps."""
        text_lower = text.lower()
        indicators = []
        if "indemnif" in text_lower:
            indicators.append("indemnification_clause")
        if "cap" in text_lower and "liability" in text_lower:
            indicators.append("liability_cap")
        if "survival" in text_lower:
            indicators.append("survival_period")
        if "basket" in text_lower or "deductible" in text_lower:
            indicators.append("basket_deductible")
        if "carve-out" in text_lower or "carve out" in text_lower:
            indicators.append("carve_out")
        # Extract cap amount
        cap_match = re.search(r"(?:cap|ceiling|limit)\s+(?:on liability|of liability|liability)\s+at\s+[\$€£¥]?\s*([\d,]+(?:\.\d{1,2})?)\s*(million|billion|thousand)?", text, re.IGNORECASE)
        cap_amount = None
        if cap_match:
            cap_amount = float(cap_match.group(1).replace(",", ""))
            mult = cap_match.group(2)
            if mult:
                if "million" in mult.lower():
                    cap_amount *= 1_000_000
                elif "billion" in mult.lower():
                    cap_amount *= 1_000_000_000
                elif "thousand" in mult.lower():
                    cap_amount *= 1_000
        return {
            "name": "indemnification_scope",
            "value": bool(indicators),
            "inputs": {"indicators": indicators, "cap_amount": cap_amount},
            "confidence": 0.85 if indicators else 0.0,
        }

    def _extract_governing_law(self, text: str) -> Dict[str, Any]:
        """Extract governing law and venue."""
        found = []
        law_match = re.search(r"(?:governed by|governing law|choice of law)[:\s]+([A-Z][a-zA-Z\s]+?)(?:\n|\.|,|;)", text, re.IGNORECASE)
        venue_match = re.search(r"(?:venue|jurisdiction)[:\s]+([A-Z][a-zA-Z\s]+?)(?:\n|\.|,|;)", text, re.IGNORECASE)
        arbitration = bool(re.search(r"\barbitration\b", text, re.IGNORECASE))

        if law_match:
            found.append({"type": "governing_law", "value": law_match.group(1).strip()})
        if venue_match:
            found.append({"type": "venue", "value": venue_match.group(1).strip()})
        if arbitration:
            found.append({"type": "dispute_resolution", "value": "arbitration"})

        return {
            "name": "governing_law",
            "value": found,
            "inputs": {"arbitration": arbitration},
            "confidence": 0.85 if found else 0.0,
        }

    def _extract_ip_ownership(self, text: str) -> Dict[str, Any]:
        """Detect IP ownership and license terms."""
        text_lower = text.lower()
        indicators = []
        if "assignment" in text_lower:
            indicators.append("assignment")
        if "license" in text_lower:
            indicators.append("license")
        if "background ip" in text_lower or "background intellectual property" in text_lower:
            indicators.append("background_ip")
        if "foreground ip" in text_lower or "foreground intellectual property" in text_lower:
            indicators.append("foreground_ip")
        if "joint ownership" in text_lower:
            indicators.append("joint_ownership")
        if "work for hire" in text_lower:
            indicators.append("work_for_hire")
        return {
            "name": "ip_ownership",
            "value": bool(indicators),
            "inputs": {"indicators": indicators},
            "confidence": 0.8 if indicators else 0.0,
        }

    def _extract_jurisdiction(self, text: str) -> Optional[str]:
        """Extract jurisdiction from governing law or court references."""
        law_match = re.search(r"(?:governed by|governing law|choice of law)[:\s]+([A-Z][a-zA-Z\s]+?)(?:\n|\.|,|;)", text, re.IGNORECASE)
        if law_match:
            return law_match.group(1).strip()[:100]
        state_match = re.search(r"State of\s+([A-Z][a-zA-Z]+)", text)
        if state_match:
            return state_match.group(1).strip()[:100]
        return None

    # ------------------------------------------------------------------
    # COMPLIANCE & REGULATORY CHECKING (private)
    # ------------------------------------------------------------------

    def _check_gdpr(self, text: str) -> Dict[str, Any]:
        """Detect GDPR concepts."""
        text_lower = text.lower()
        keywords = ["data processing", "consent", "data transfer", "dpa", "data processing agreement", "standard contractual clauses", "scc", "adequacy decision", "gdpr"]
        found = [kw for kw in keywords if kw in text_lower]
        return {"regulation": "gdpr", "detected": bool(found), "keywords_found": found, "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0}

    def _check_ccpa(self, text: str) -> Dict[str, Any]:
        """Detect CCPA concepts."""
        text_lower = text.lower()
        keywords = ["consumer rights", "opt-out", "sale of personal information", "service provider", "business purpose", "ccpa", "california consumer privacy"]
        found = [kw for kw in keywords if kw in text_lower]
        return {"regulation": "ccpa", "detected": bool(found), "keywords_found": found, "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0}

    def _check_anti_bribery(self, text: str) -> Dict[str, Any]:
        """Detect anti-bribery concepts."""
        text_lower = text.lower()
        keywords = ["fcpa", "uk bribery act", "facilitation payment", "government official", "third-party due diligence", "anti-bribery", "anti corruption"]
        found = [kw for kw in keywords if kw in text_lower]
        return {"regulation": "anti_bribery", "detected": bool(found), "keywords_found": found, "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0}

    def _check_antitrust(self, text: str) -> Dict[str, Any]:
        """Detect antitrust concepts."""
        text_lower = text.lower()
        keywords = ["price fixing", "market allocation", "bid rigging", "non-compete", "exclusivity", "most favored nation", "mfn", "antitrust"]
        found = [kw for kw in keywords if kw in text_lower]
        return {"regulation": "antitrust", "detected": bool(found), "keywords_found": found, "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0}

    def _check_sanctions(self, text: str) -> Dict[str, Any]:
        """Detect sanctions/export control concepts."""
        text_lower = text.lower()
        keywords = ["ofac", "sdn list", "embargo", "blocked person", "export control", "restricted party", "sanctions"]
        found = [kw for kw in keywords if kw in text_lower]
        return {"regulation": "sanctions", "detected": bool(found), "keywords_found": found, "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0}

    def _check_securities(self, text: str) -> Dict[str, Any]:
        """Detect securities compliance concepts."""
        text_lower = text.lower()
        keywords = ["sec filing", "10-k", "10-q", "8-k", "material contract", "insider trading", "disclosure obligation", "securities act"]
        found = [kw for kw in keywords if kw in text_lower]
        return {"regulation": "securities", "detected": bool(found), "keywords_found": found, "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0}

    # ------------------------------------------------------------------
    # RISK SCORING (private)
    # ------------------------------------------------------------------

    def _score_litigation_risk(self, text: str) -> Dict[str, Any]:
        """Score litigation risk."""
        text_lower = text.lower()
        indicators = ["dispute resolution", "arbitration", "jury waiver", "class action waiver", "forum selection", "litigation", "lawsuit"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {"category": "litigation_risk", "score": round(score, 2), "level": self._risk_level(score), "indicators": found, "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0}

    def _score_regulatory_risk(self, text: str) -> Dict[str, Any]:
        """Score regulatory risk."""
        text_lower = text.lower()
        indicators = ["regulated industry", "licensing requirement", "reporting obligation", "enforcement exposure", "regulatory investigation", "compliance"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {"category": "regulatory_risk", "score": round(score, 2), "level": self._risk_level(score), "indicators": found, "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0}

    def _score_reputational_risk(self, text: str) -> Dict[str, Any]:
        """Score reputational risk."""
        text_lower = text.lower()
        indicators = ["public disclosure", "media coverage", "whistleblower", "regulatory investigation", "scandal", "reputational harm"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {"category": "reputational_risk", "score": round(score, 2), "level": self._risk_level(score), "indicators": found, "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0}

    def _score_financial_risk(self, text: str) -> Dict[str, Any]:
        """Score financial risk."""
        text_lower = text.lower()
        indicators = ["unlimited liability", "uncapped indemnity", "personal guarantee", "onerous payment", "liquidated damages", "penalty"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {"category": "financial_risk", "score": round(score, 2), "level": self._risk_level(score), "indicators": found, "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0}

    def _score_ip_risk(self, text: str) -> Dict[str, Any]:
        """Score IP risk."""
        text_lower = text.lower()
        indicators = ["unclear ownership", "broad license", "weak confidentiality", "open source", "contamination", "assignment", "work for hire"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {"category": "ip_risk", "score": round(score, 2), "level": self._risk_level(score), "indicators": found, "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0}

    def _compute_overall_risk(self, text: str) -> Dict[str, Any]:
        """Combine individual risk scores into an overall score."""
        litigation = self._score_litigation_risk(text)
        regulatory = self._score_regulatory_risk(text)
        reputational = self._score_reputational_risk(text)
        financial = self._score_financial_risk(text)
        ip = self._score_ip_risk(text)
        avg = (litigation["score"] + regulatory["score"] + reputational["score"] + financial["score"] + ip["score"]) / 5.0
        return {
            "category": "overall_risk",
            "score": round(avg, 2),
            "level": self._risk_level(avg),
            "indicators": litigation["indicators"] + regulatory["indicators"] + reputational["indicators"] + financial["indicators"] + ip["indicators"],
            "confidence": round(min(litigation["confidence"], regulatory["confidence"], reputational["confidence"], financial["confidence"], ip["confidence"]), 2),
        }

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # EMPTY RESULT
    # ------------------------------------------------------------------
