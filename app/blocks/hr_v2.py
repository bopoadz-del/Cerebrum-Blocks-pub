"""HR Block v2 - TypedBlock implementation

This is the v2 implementation that:
- Extends TypedBlock instead of UniversalContainer
- Accepts TextContent input (from pdf_v2, ocr_v2, etc.)
- Outputs HRAnalysis type
- Has a single process() entry point instead of action routing
- Internal methods are private (_ prefixed)
- Uses deterministic regex + math, no LLM calls, no external APIs
"""

import re
from typing import Any, Dict, List, Optional

from app.core.domain_block_v2 import DomainBlockV2
from app.core.schema_registry import TextContent, HRAnalysis
from app.core.hr_types import RiskScore

from app.core.hr_knowledge import HRKnowledge, COMPLIANCE_KEYWORDS
from app.core.http_errors import error_kind

_rk = HRKnowledge()


class HRBlockV2(DomainBlockV2):
    """
    HR Block v2 - TypedBlock implementation for hr document analysis.

    Input: TextContent (extracted document text)
    Output: HRAnalysis (entities, metrics, compliance flags, risk scores)
    """

    name = "hr_v2"
    version = "2.0"
    description = "HR document analysis with typed input/output"
    layer = 3
    tags = ["domain", "hr", "v2"]
    requires = []

    default_config = {
        "confidence_threshold": 0.85,
    }

    input_schema = TextContent
    output_schema = HRAnalysis

    accepted_input_types = ["TextContent", "PDFContent"]
    produced_output_types = ["HRAnalysis"]

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste HR document text...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "time_to_fill", "type": "number", "label": "Time to Fill (days)"},
                {"name": "cost_per_hire", "type": "number", "label": "Cost per Hire"},
                {"name": "turnover_rate", "type": "number", "label": "Turnover Rate %"},
                {"name": "offer_acceptance_rate", "type": "number", "label": "Offer Acceptance %"},
                {"name": "litigation_risk", "type": "number", "label": "Litigation Risk"},
                {"name": "talent_retention_risk", "type": "number", "label": "Talent Retention Risk"},
                {"name": "compliance_risk", "type": "number", "label": "Compliance Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze Employment Contract", "prompt": "Analyze this employment contract"},
            {"icon": "⚖️", "label": "Check EEO Compliance", "prompt": "Check this document for EEO compliance"},
            {"icon": "⚠️", "label": "Score HR Risks", "prompt": "Score HR risks for this document"},
            {"icon": "🔍", "label": "Extract Salaries & Dates", "prompt": "Extract salaries and dates from this document"},
        ],
    }

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Main entry point - analyze hr document text."""
        params = params or {}

        text = self._extract_text(input_data)
        if not text:
            return self._empty_analysis("No text provided")

        custom_rules = params.get("custom_rules") or params.get("rules")
        if custom_rules:
            _rk.set_custom_rules(custom_rules)

        document_type = params.get("document_type") or params.get("analysis_type") or self._detect_document_type(text)

        if document_type == "employment_contract":
            return await self._analyze_employment_contract(text, params)
        if document_type == "performance_review":
            return await self._analyze_performance_review(text, params)
        if document_type == "job_description":
            return await self._analyze_job_description(text, params)
        if document_type == "recruitment_pipeline":
            return await self._analyze_recruitment_pipeline(text, params)
        if document_type == "termination_notice":
            return await self._analyze_termination_notice(text, params)
        if document_type == "benefits_enrollment":
            return await self._analyze_benefits_enrollment(text, params)
        if document_type == "disciplinary_action":
            return await self._analyze_disciplinary_action(text, params)
        if document_type == "payroll_record":
            return await self._analyze_payroll_record(text, params)

        return await self._analyze_generic(text, params)

    # ------------------------------------------------------------------
    # TEXT EXTRACTION
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DOCUMENT TYPE DETECTION
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        """Auto-detect hr document type from content."""
        text_lower = text[:5000].lower()

        if any(kw in text_lower for kw in ['employment', 'offer letter', 'salary', 'start date', 'probation', 'termination', 'notice period']):
            return "employment_contract"
        if any(kw in text_lower for kw in ['performance', 'appraisal', 'kpi', 'goals', 'rating', 'improvement plan', '360 feedback']):
            return "performance_review"
        if any(kw in text_lower for kw in ['job description', 'jd', 'responsibilities', 'qualifications', 'experience', 'reporting line', 'flsa']):
            return "job_description"
        if any(kw in text_lower for kw in ['candidate', 'resume', 'interview', 'assessment', 'background check', 'reference', 'offer']):
            return "recruitment_pipeline"
        if any(kw in text_lower for kw in ['termination', 'dismissal', 'redundancy', 'layoff', 'severance', 'exit interview', 'garden leave']):
            return "termination_notice"
        if any(kw in text_lower for kw in ['benefits', 'health insurance', '401k', 'pension', 'pto', 'fsa', 'hsa', 'enrollment', 'dependent']):
            return "benefits_enrollment"
        if any(kw in text_lower for kw in ['disciplinary', 'warning', 'pip', 'suspension', 'grievance', 'appeal', 'union']):
            return "disciplinary_action"
        if any(kw in text_lower for kw in ['payroll', 'timesheet', 'overtime', 'bonus', 'commission', 'deduction', 'ytd', 'w-2', 'payslip']):
            return "payroll_record"

        return "generic"

    # ------------------------------------------------------------------
    # ANALYSIS METHODS (private)
    # ------------------------------------------------------------------

    async def _analyze_employment_contract(self, text: str, params: Dict) -> Dict:
        """Analyze employment contract text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "employment_contract"
        return self._finalize_result(result, params)

    async def _analyze_performance_review(self, text: str, params: Dict) -> Dict:
        """Analyze performance review text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "performance_review"
        return self._finalize_result(result, params)

    async def _analyze_job_description(self, text: str, params: Dict) -> Dict:
        """Analyze job description text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "job_description"
        return self._finalize_result(result, params)

    async def _analyze_recruitment_pipeline(self, text: str, params: Dict) -> Dict:
        """Analyze recruitment pipeline text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "recruitment_pipeline"
        return self._finalize_result(result, params)

    async def _analyze_termination_notice(self, text: str, params: Dict) -> Dict:
        """Analyze termination notice text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "termination_notice"
        return self._finalize_result(result, params)

    async def _analyze_benefits_enrollment(self, text: str, params: Dict) -> Dict:
        """Analyze benefits enrollment text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "benefits_enrollment"
        return self._finalize_result(result, params)

    async def _analyze_disciplinary_action(self, text: str, params: Dict) -> Dict:
        """Analyze disciplinary action text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "disciplinary_action"
        return self._finalize_result(result, params)

    async def _analyze_payroll_record(self, text: str, params: Dict) -> Dict:
        """Analyze payroll record text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "payroll_record"
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
            "employee_ids": self._extract_employee_ids(text),
            "candidate_names": self._extract_candidate_names(text),
            "job_titles": self._extract_job_titles(text),
            "departments": self._extract_departments(text),
            "salary_figures": self._extract_salary_figures(text),
            "start_dates": self._extract_start_dates(text),
            "managers": self._extract_managers(text),
            "locations": self._extract_locations(text),
        }
        metrics = {
            "time_to_fill": self._extract_time_to_fill(**params.get("time_to_fill", {})),
            "cost_per_hire": self._extract_cost_per_hire(**params.get("cost_per_hire", {})),
            "offer_acceptance_rate": self._extract_offer_acceptance_rate(**params.get("offer_acceptance_rate", {})),
            "turnover_rate": self._extract_turnover_rate(**params.get("turnover_rate", {})),
            "voluntary_turnover": self._extract_voluntary_turnover(**params.get("voluntary_turnover", {})),
            "absenteeism_rate": self._extract_absenteeism_rate(**params.get("absenteeism_rate", {})),
            "overtime_rate": self._extract_overtime_rate(**params.get("overtime_rate", {})),
            "compensation_ratio": self._extract_compensation_ratio(**params.get("compensation_ratio", {})),
        }
        compliance_flags = {
            "equal_employment_opportunity": self._check_equal_employment_opportunity(text),
            "fair_labor_standards": self._check_fair_labor_standards(text),
            "gdpr": self._check_gdpr(text),
            "osha": self._check_osha(text),
            "immigration": self._check_immigration(text),
        }
        risk_scores = {
            "litigation_risk": self._score_litigation_risk(text),
            "talent_retention_risk": self._score_talent_retention_risk(text),
            "compliance_risk": self._score_compliance_risk(text),
            "reputation_risk": self._score_reputation_risk(text),
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
                "company_name": self._extract_company_name(text),
            },
        }

    def _extract_company_name(self, text: str) -> Optional[str]:
        """Best-effort extraction of company name."""
        pattern = r"(?:company name|company_name)[:\s]+([A-Z][A-Za-z0-9\s&.,-]{2,60})"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            return match.group(1).strip()
        return None

    # ------------------------------------------------------------------
    # ENTITY EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_employee_ids(self, text: str) -> List[Dict]:
        """Extract employee ids from text."""
        found = []
        for match in re.finditer(r"(?:employee\s*id|eid|staff\s*number)\s*#?\s*(\d{6,12})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "employee_ids",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_candidate_names(self, text: str) -> List[Dict]:
        """Extract candidate names from text."""
        found = []
        for match in re.finditer(r"(?:candidate|applicant)\s*[\-:]?\s*([A-Z][A-Za-z\s\.]+)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "candidate_names",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_job_titles(self, text: str) -> List[Dict]:
        """Extract job titles from text."""
        found = []
        for match in re.finditer(r"(?:job title|position|role|designation|rank)\s*[\-:]?\s*([A-Z][A-Za-z\s\-/]+)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "job_titles",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_departments(self, text: str) -> List[Dict]:
        """Extract departments from text."""
        found = []
        for match in re.finditer(r"(?:department|division|business unit|team|function)\s*[\-:]?\s*([A-Z][A-Za-z\s]+)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "departments",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_salary_figures(self, text: str) -> List[Dict]:
        """Extract salary figures from text."""
        found = []
        for match in re.finditer(r"(?:\$)\s*([\d,]+(?:\.\d{1,2})?)\s*(?:per year|annually|monthly|hourly|/yr|/mo|/hr)?", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "salary_figures",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_start_dates(self, text: str) -> List[Dict]:
        """Extract start dates from text."""
        found = []
        for match in re.finditer(r"(?:start date|commencement|effective date|date of hire)\s*[\-:]?\s*(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "start_dates",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_managers(self, text: str) -> List[Dict]:
        """Extract managers from text."""
        found = []
        for match in re.finditer(r"(?:reports to|manager|supervisor|team lead|director|vp)\s*[\-:]?\s*([A-Z][A-Za-z\s\.]+)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "managers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_locations(self, text: str) -> List[Dict]:
        """Extract locations from text."""
        found = []
        for match in re.finditer(r"(?:office location|location|remote|hybrid|site|branch|region)\s*[\-:]?\s*([A-Z][A-Za-z\s,]+)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "locations",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    # ------------------------------------------------------------------
    # METRICS & FORMULA EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_time_to_fill(self, open_date=None, fill_date=None) -> Dict[str, Any]:
        """Calculate time to fill."""
        try:
            value = self._days_between(open_date, fill_date) if (open_date is not None and fill_date is not None) else None
            if value is None:
                return {"name": "time_to_fill", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "time_to_fill", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "time_to_fill", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_cost_per_hire(self, total_recruitment_cost=None, hires=None) -> Dict[str, Any]:
        """Calculate cost per hire."""
        try:
            value = self._safe_divide(total_recruitment_cost, hires) if (total_recruitment_cost is not None and hires is not None) else None
            if value is None:
                return {"name": "cost_per_hire", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "cost_per_hire", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "cost_per_hire", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_offer_acceptance_rate(self, accepted_offers=None, total_offers=None) -> Dict[str, Any]:
        """Calculate offer acceptance rate."""
        try:
            value = self._safe_divide(accepted_offers, total_offers, scale=100) if (accepted_offers is not None and total_offers is not None) else None
            if value is None:
                return {"name": "offer_acceptance_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "offer_acceptance_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "offer_acceptance_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_turnover_rate(self, terminations=None, average_headcount=None) -> Dict[str, Any]:
        """Calculate turnover rate."""
        try:
            value = self._safe_divide(terminations, average_headcount, scale=100) if (terminations is not None and average_headcount is not None) else None
            if value is None:
                return {"name": "turnover_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "turnover_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "turnover_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_voluntary_turnover(self, voluntary_terms=None, total_terms=None) -> Dict[str, Any]:
        """Calculate voluntary turnover."""
        try:
            value = self._safe_divide(voluntary_terms, total_terms, scale=100) if (voluntary_terms is not None and total_terms is not None) else None
            if value is None:
                return {"name": "voluntary_turnover", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "voluntary_turnover", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "voluntary_turnover", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_absenteeism_rate(self, absent_days=None, total_work_days=None) -> Dict[str, Any]:
        """Calculate absenteeism rate."""
        try:
            value = self._safe_divide(absent_days, total_work_days, scale=100) if (absent_days is not None and total_work_days is not None) else None
            if value is None:
                return {"name": "absenteeism_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "absenteeism_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "absenteeism_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_overtime_rate(self, overtime_hours=None, total_hours=None) -> Dict[str, Any]:
        """Calculate overtime rate."""
        try:
            value = self._safe_divide(overtime_hours, total_hours, scale=100) if (overtime_hours is not None and total_hours is not None) else None
            if value is None:
                return {"name": "overtime_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "overtime_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "overtime_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_compensation_ratio(self, employee_salary=None, market_median=None) -> Dict[str, Any]:
        """Calculate compensation ratio."""
        try:
            value = self._safe_divide(employee_salary, market_median, scale=100) if (employee_salary is not None and market_median is not None) else None
            if value is None:
                return {"name": "compensation_ratio", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "compensation_ratio", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "compensation_ratio", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    # ------------------------------------------------------------------
    # REGULATORY & COMPLIANCE CHECKING (private)
    # ------------------------------------------------------------------

    def _check_equal_employment_opportunity(self, text: str) -> Dict[str, Any]:
        """Check equal employment opportunity compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["equal_employment_opportunity"] if kw in text.lower()]
        return {
            "regulation": "equal_employment_opportunity",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_fair_labor_standards(self, text: str) -> Dict[str, Any]:
        """Check fair labor standards compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["fair_labor_standards"] if kw in text.lower()]
        return {
            "regulation": "fair_labor_standards",
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

    def _check_osha(self, text: str) -> Dict[str, Any]:
        """Check osha compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["osha"] if kw in text.lower()]
        return {
            "regulation": "osha",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_immigration(self, text: str) -> Dict[str, Any]:
        """Check immigration compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["immigration"] if kw in text.lower()]
        return {
            "regulation": "immigration",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    # ------------------------------------------------------------------
    # RISK SCORING (private)
    # ------------------------------------------------------------------

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

    def _score_talent_retention_risk(self, text: str) -> RiskScore:
        """Score talent retention risk."""
        data = _rk.check_risk_keywords(text).get("talent_retention_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="talent_retention_risk",
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
