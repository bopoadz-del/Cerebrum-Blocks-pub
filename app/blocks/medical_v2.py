"""Medical Block v2 - TypedBlock implementation

This is the v2 implementation that:
- Extends TypedBlock instead of UniversalContainer
- Accepts TextContent input (from pdf_v2, ocr_v2, etc.)
- Outputs MedicalAnalysis type
- Has a single process() entry point instead of action routing
- Internal methods are private (_ prefixed)
- Uses deterministic regex + math, no LLM calls, no external APIs
- Redacts PHI before returning it
"""

import re
import math
from typing import Any, Dict, List, Optional, Tuple

from app.core.domain_block_v2 import DomainBlockV2
from app.core.schema_registry import TextContent, MedicalAnalysis

from app.core.medical_knowledge import MedicalKnowledge
from app.core.http_errors import error_kind

_mk = MedicalKnowledge()


class MedicalBlockV2(DomainBlockV2):
    """
    Medical Block v2 - TypedBlock implementation for healthcare document analysis.

    Input: TextContent (extracted document text)
    Output: MedicalAnalysis (entities, clinical metrics, compliance flags, risk scores)

    PHI is detected but returned in redacted/tokenized form to avoid leaking
    patient identifiers.
    """

    name = "medical_v2"
    version = "2.0"
    description = "Healthcare document analysis with typed input/output and PHI redaction"
    layer = 3
    tags = ["domain", "medical", "healthcare", "v2", "phi-safe"]
    requires = []

    default_config = {
        "confidence_threshold": 0.85,
        "redact_phi": True,
    }

    # Input: TextContent from pdf_v2, ocr_v2, etc.
    input_schema = TextContent

    # Output: MedicalAnalysis
    output_schema = MedicalAnalysis

    # Type declarations for orchestrator
    accepted_input_types = ["TextContent", "PDFContent"]
    produced_output_types = ["MedicalAnalysis"]

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste medical document text...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "bmi", "type": "number", "label": "BMI"},
                {"name": "egfr", "type": "number", "label": "eGFR", "unit": "mL/min/1.73m²"},
                {"name": "cardiac_risk", "type": "percentage", "label": "Cardiac Risk"},
                {"name": "glasgow_score", "type": "number", "label": "GCS"},
                {"name": "readmission_risk", "type": "number", "label": "Readmission Risk"},
                {"name": "medication_error_risk", "type": "number", "label": "Med Error Risk"},
                {"name": "infection_risk", "type": "number", "label": "Infection Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📝", "label": "Analyze Clinical Note", "prompt": "Analyze this clinical note"},
            {"icon": "🔒", "label": "Check HIPAA Compliance", "prompt": "Check this document for HIPAA compliance"},
            {"icon": "⚠️", "label": "Score Clinical Risks", "prompt": "Score clinical risks for this patient document"},
            {"icon": "💊", "label": "Extract Medications", "prompt": "Extract medications and dosages from this document"},
        ],
    }

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """
        Main entry point - analyze healthcare document text.

        Input: TextContent dict (or string for backward compatibility)
        Output: MedicalAnalysis dict
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
        knowledge = MedicalKnowledge()
        if custom_rules:
            knowledge.set_custom_rules(custom_rules)
        # Per-request slot: fresh instance every process() call, so a
        # reused block instance never leaks one request's rules into the
        # next (the old module-level singleton did).
        self._request_knowledge = knowledge

        # Determine analysis type from params or auto-detect
        document_type = params.get("document_type") or params.get("analysis_type") or self._detect_document_type(text)

        # Run analysis based on type
        if document_type == "clinical_note":
            return await self._analyze_clinical_note(text, params)
        elif document_type == "discharge_summary":
            return await self._analyze_discharge_summary(text, params)
        elif document_type == "lab_report":
            return await self._analyze_lab_report(text, params)
        elif document_type == "radiology_report":
            return await self._analyze_radiology_report(text, params)
        elif document_type == "pathology_report":
            return await self._analyze_pathology_report(text, params)
        elif document_type == "prescription":
            return await self._analyze_prescription(text, params)
        elif document_type == "insurance_claim":
            return await self._analyze_insurance_claim(text, params)
        elif document_type == "consent_form":
            return await self._analyze_consent_form(text, params)
        elif document_type == "clinical_trial":
            return await self._analyze_clinical_trial(text, params)
        else:
            return await self._analyze_generic(text, params)

    # ------------------------------------------------------------------
    # TEXT EXTRACTION
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DOCUMENT TYPE DETECTION
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        """Auto-detect medical document type from content."""
        text_lower = text[:5000].lower()

        # Clinical note — checked before prescription because notes contain medication terms
        if any(kw in text_lower for kw in ["soap", "subjective", "objective", "assessment", "plan", "hpi", "ros", "physical exam", "clinical note"]):
            return "clinical_note"

        # Prescription
        prescription_keywords = ["prescription", "dispense", "refills", "pharmacy"]
        if any(kw in text_lower for kw in prescription_keywords):
            return "prescription"
        if re.search(r"\b(rx|sig)\b", text_lower):
            return "prescription"

        # Insurance claim
        if any(kw in text_lower for kw in ["claim", "cpt", "icd-10", "diagnosis code", "procedure code", "prior authorization", "eob", "explanation of benefits"]):
            return "insurance_claim"

        # Clinical trial
        if any(kw in text_lower for kw in ["protocol", "inclusion criteria", "exclusion criteria", "adverse event", "ctcae", "sponsor", "principal investigator", "clinical trial"]):
            return "clinical_trial"

        # Consent form
        if any(kw in text_lower for kw in ["informed consent", "risks", "benefits", "alternatives", "patient signature", "witness"]):
            return "consent_form"

        # Discharge summary
        if any(kw in text_lower for kw in ["discharge", "admission date", "discharge date", "hospital course", "discharge instructions", "follow-up"]):
            return "discharge_summary"

        # Lab report
        if any(kw in text_lower for kw in ["laboratory", "cbc", "bmp", "cmp", "lipid panel", "hemoglobin", "wbc", "glucose", "reference range"]):
            return "lab_report"

        # Radiology report
        if any(kw in text_lower for kw in ["radiology", "x-ray", "ct", "mri", "ultrasound", "impression", "findings", "contrast"]):
            return "radiology_report"

        # Pathology report
        if any(kw in text_lower for kw in ["pathology", "histology", "biopsy", "specimen", "diagnosis", "margins", "grade", "stage"]):
            return "pathology_report"

        # Clinical note
        if any(kw in text_lower for kw in ["soap", "subjective", "objective", "assessment", "plan", "hpi", "ros", "physical exam"]):
            return "clinical_note"

        return "generic"

    # ------------------------------------------------------------------
    # ANALYSIS METHODS (private)
    # ------------------------------------------------------------------

    async def _analyze_clinical_note(self, text: str, params: Dict) -> Dict:
        """Analyze clinical note text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "clinical_note"
        return self._finalize_result(result, params)

    async def _analyze_discharge_summary(self, text: str, params: Dict) -> Dict:
        """Analyze discharge summary text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "discharge_summary"
        return self._finalize_result(result, params)

    async def _analyze_lab_report(self, text: str, params: Dict) -> Dict:
        """Analyze lab report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "lab_report"
        return self._finalize_result(result, params)

    async def _analyze_radiology_report(self, text: str, params: Dict) -> Dict:
        """Analyze radiology report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "radiology_report"
        return self._finalize_result(result, params)

    async def _analyze_pathology_report(self, text: str, params: Dict) -> Dict:
        """Analyze pathology report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "pathology_report"
        return self._finalize_result(result, params)

    async def _analyze_prescription(self, text: str, params: Dict) -> Dict:
        """Analyze prescription text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "prescription"
        return self._finalize_result(result, params)

    async def _analyze_insurance_claim(self, text: str, params: Dict) -> Dict:
        """Analyze insurance claim text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "insurance_claim"
        return self._finalize_result(result, params)

    async def _analyze_consent_form(self, text: str, params: Dict) -> Dict:
        """Analyze consent form text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "consent_form"
        return self._finalize_result(result, params)

    async def _analyze_clinical_trial(self, text: str, params: Dict) -> Dict:
        """Analyze clinical trial document text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "clinical_trial"
        return self._finalize_result(result, params)

    async def _analyze_generic(self, text: str, params: Dict) -> Dict:
        """Generic analysis for unknown medical document types."""
        result = self._build_analysis(text, params)
        result["document_type"] = "generic"
        return self._finalize_result(result, params)

    # ------------------------------------------------------------------
    # BUILDERS
    # ------------------------------------------------------------------

    def _build_analysis(self, text: str, params: Dict) -> Dict:
        """Run all extraction passes and return a working dict."""
        entities = {
            "patient_id": self._extract_patient_id(text),
            "dob": self._extract_dates_of_birth(text),
            "diagnoses": self._extract_diagnoses(text),
            "medications": self._extract_medications(text),
            "allergies": self._extract_allergies(text),
            "vitals": self._extract_vitals(text),
            "procedures": self._extract_procedures(text),
            "providers": self._extract_providers(text),
            "facilities": self._extract_facilities(text),
        }
        clinical_metrics = self._calculate_clinical_metrics(text, params)
        compliance_flags = {
            "hipaa": self._check_hipaa(text),
            "fda_21_cfr": self._check_fda_21_cfr(text),
            "clinical_trial": self._check_clinical_trial_compliance(text),
            "gdpr": self._check_gdpr_health(text),
            "joint_commission": self._check_joint_commission(text),
        }
        risk_scores = {
            "readmission": self._score_readmission_risk(text),
            "medication_error": self._score_medication_error_risk(text),
            "infection": self._score_infection_risk(text),
            "fall": self._score_fall_risk(text),
            "mortality": self._score_mortality_risk(text),
            "overall_risk": self._compute_overall_risk(text),
        }
        risk_scores_note = (
            "heuristic keyword scoring — unvalidated, no clinical authority; "
            "not a clinical decision instrument"
        )
        custom_rule_hits = self._request_knowledge.check_custom_rules(text)
        document_date = self._extract_document_date(text)

        return {
            "document_type": "unknown",
            "entities": entities,
            "clinical_metrics": clinical_metrics,
            "compliance_flags": compliance_flags,
            "risk_scores": risk_scores,
            "risk_scores_note": risk_scores_note,
            "custom_rule_hits": custom_rule_hits,
            "text": text,
            "raw_text": "",
            "metadata": {
                "extracted_at": self._timestamp(),
                "entity_count": sum(len(v) for v in entities.values()),
                "metric_count": sum(1 for v in clinical_metrics.values() if v and v.get("value") is not None),
                "document_date": document_date,
                "phi_redacted": params.get("redact_phi", self.default_config["redact_phi"]),
            },
        }

    # ------------------------------------------------------------------
    # PHI-SAFE HELPERS
    # ------------------------------------------------------------------

    def _redacted_entity(self, entity_type: str, original_format: str = "", count: int = 1) -> Dict:
        """Return a redacted PHI entity placeholder."""
        return {
            "type": entity_type,
            "value": "REDACTED",
            "original_format": original_format,
            "count": count,
            "confidence": 0.9,
            "context": "",
            "metadata": {"redacted": True},
        }

    def _phi_context(self, text: str, start: int, end: int, radius: int = 0) -> str:
        """Return empty context for PHI fields (no leakage)."""
        return ""

    # ------------------------------------------------------------------
    # ENTITY EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_patient_id(self, text: str) -> List[Dict]:
        """Detect patient identifiers and return redacted placeholders."""
        patterns = [
            r"\b(?:MRN|Medical Record Number|Patient ID|Patient #:?)\s*:?\s*\d{6,10}\b",
            r"\b\d{6,10}\s*(?:MRN|medical record)\b",
        ]
        count = 0
        for pattern in patterns:
            count += len(re.findall(pattern, text, re.IGNORECASE))
        if count:
            return [self._redacted_entity("patient_id", "MRN/Patient ID", count)]
        return []

    def _extract_dates_of_birth(self, text: str) -> List[Dict]:
        """Detect dates of birth and return redacted placeholders."""
        patterns = [
            r"\b(?:DOB|Date of Birth|Birth Date)[:\s]+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
            r"\b(?:DOB|Date of Birth)[:\s]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b",
        ]
        count = 0
        for pattern in patterns:
            count += len(re.findall(pattern, text, re.IGNORECASE))
        if count:
            return [self._redacted_entity("dob", "DOB", count)]
        return []

    def _extract_diagnoses(self, text: str) -> List[Dict]:
        """Extract ICD-10 codes and common diagnosis keywords."""
        found = []

        # ICD-10 codes
        icd_pattern = r"\b[A-Z]\d{2}(?:\.\d{1,2})?\b"
        for match in re.finditer(icd_pattern, text):
            code = match.group(0)
            # Basic ICD-10 sanity: first char is A-Z (not I, O, U in standard but accept broadly)
            if code[0].isalpha() and code[0].upper() not in {"I", "O", "U", "X", "Y", "Z"} or code[0].upper() in {"A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M", "N", "P", "Q", "R", "S", "T", "V", "W"}:
                found.append({
                    "type": "icd10",
                    "value": code,
                    "confidence": 0.9,
                    "context": text[max(0, match.start() - 30):match.end() + 30],
                })

        # Common diagnoses
        common_diagnoses = [
            "diabetes", "type 1 diabetes", "type 2 diabetes", "hypertension",
            "copd", "chf", "congestive heart failure", "cancer", "asthma",
            "pneumonia", "stroke", "myocardial infarction", "atrial fibrillation",
            "depression", "anxiety", "chronic kidney disease", "ckd", "anemia"
        ]
        text_lower = text.lower()
        for dx in common_diagnoses:
            if dx in text_lower:
                idx = text_lower.find(dx)
                found.append({
                    "type": "diagnosis",
                    "value": dx,
                    "confidence": 0.8,
                    "context": text[max(0, idx - 30):idx + len(dx) + 30],
                })

        return self._deduplicate_entities(found)

    def _extract_medications(self, text: str) -> List[Dict]:
        """Extract medication names with dosage and frequency."""
        common_meds = [
            "metformin", "lisinopril", "atorvastatin", "amoxicillin", "azithromycin",
            "omeprazole", "levothyroxine", "amlodipine", "metoprolol", "losartan",
            "albuterol", "gabapentin", "hydrochlorothiazide", "sertraline", "fluoxetine",
            "ibuprofen", "acetaminophen", "aspirin", "warfarin", "apixaban",
            "insulin", "furosemide", "pantoprazole", "prednisone", "tramadol",
            "oxycodone", "morphine", "ondansetron", "cephalexin", "ciprofloxacin"
        ]
        found = []
        text_lower = text.lower()

        for med in common_meds:
            for match in re.finditer(rf"\b{med}\b", text_lower):
                start = match.start()
                end = match.end()
                window = text[end:end + 60]
                dose_match = re.search(r"(\d+(?:\.\d+)?\s*(?:mg|mcg|g|units?|tablet|cap|ml))", window, re.IGNORECASE)
                freq_match = re.search(r"((?:once|twice|three times|four times|daily|bid|tid|qid|q\d+h|prn|nightly|morning|evening)\s*(?:daily|a day|per day)?)", window, re.IGNORECASE)
                metadata = {}
                if dose_match:
                    metadata["dose"] = dose_match.group(1)
                if freq_match:
                    metadata["frequency"] = freq_match.group(1)
                found.append({
                    "type": "medication",
                    "value": med,
                    "confidence": 0.9,
                    "context": text[max(0, start - 20):end + 60],
                    "metadata": metadata,
                })

        # Generic Rx pattern: medication + dose + frequency
        rx_pattern = r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(\d+(?:\.\d+)?\s*(?:mg|mcg|g|units?|tablet|cap|ml))\s+((?:once|twice|three times|four times|daily|bid|tid|qid|q\d+h|prn|nightly))"
        for match in re.finditer(rx_pattern, text):
            name = match.group(1)
            if name.lower() not in common_meds and len(name) > 3:
                found.append({
                    "type": "medication",
                    "value": name,
                    "confidence": 0.75,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                    "metadata": {"dose": match.group(2), "frequency": match.group(3)},
                })

        return self._deduplicate_entities(found)

    def _extract_allergies(self, text: str) -> List[Dict]:
        """Extract allergy mentions."""
        found = []
        text_lower = text.lower()

        # NKDA
        if "nkda" in text_lower or "no known drug allergies" in text_lower:
            found.append({
                "type": "allergy",
                "value": "No known drug allergies",
                "confidence": 0.95,
                "context": text[max(0, text_lower.find("nkda") - 20):text_lower.find("nkda") + 30] if "nkda" in text_lower else "",
            })

        # Allergy list pattern
        allergy_pattern = r"(?:allergies|allergic to|allergy)[:\s]+([A-Za-z0-9\s,]+)(?:\n|$|;)"
        for match in re.finditer(allergy_pattern, text, re.IGNORECASE):
            items = [item.strip() for item in match.group(1).split(",") if item.strip()]
            for item in items[:10]:
                if len(item) > 1:
                    found.append({
                        "type": "allergy",
                        "value": item,
                        "confidence": 0.85,
                        "context": text[max(0, match.start() - 20):match.end() + 20],
                    })

        return self._deduplicate_entities(found)

    def _extract_vitals(self, text: str) -> List[Dict]:
        """Extract vital signs."""
        found = []

        patterns = {
            "bp": r"(?:BP|blood pressure)[:\s]+(\d{2,3}/\d{2,3})",
            "hr": r"(?:HR|heart rate|pulse)[:\s]+(\d{2,3})\b",
            "temp": r"\b(?:Temp(?:erature)?)[:\s]+(\d{2,3}(?:\.\d)?)\s*(?:F|C)?",
            "rr": r"(?:RR|respiratory rate|respirations)[:\s]+(\d{1,2})\b",
            "spo2": r"(?:SpO2|O2 sat|saturation)[:\s]+(\d{2,3})%?",
            "weight": r"(?:weight|wt)[:\s]+(\d+(?:\.\d+)?)\s*(?:kg|lbs?|pounds?)",
            "height": r"(?:height|ht)[:\s]+(\d+(?:\.\d+)?)\s*(?:cm|m|ft|in)",
        }

        for vital_type, pattern in patterns.items():
            for match in re.finditer(pattern, text, re.IGNORECASE):
                found.append({
                    "type": vital_type,
                    "value": match.group(1),
                    "confidence": 0.9,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })

        return found

    def _extract_procedures(self, text: str) -> List[Dict]:
        """Extract CPT codes and procedure keywords."""
        found = []

        # CPT codes (5 digits)
        cpt_pattern = r"\b\d{5}\b"
        for match in re.finditer(cpt_pattern, text):
            code = match.group(0)
            # Avoid years / room numbers by requiring CPT context
            ctx = text[max(0, match.start() - 40):match.end() + 40]
            if re.search(r"\b(cpt|procedure|surgery|code)\b", ctx, re.IGNORECASE):
                found.append({
                    "type": "cpt",
                    "value": code,
                    "confidence": 0.85,
                    "context": ctx,
                })

        # Procedure keywords
        procedure_keywords = ["surgery", "biopsy", "endoscopy", "catheterization", "injection", "colonoscopy", "laparoscopy"]
        text_lower = text.lower()
        for kw in procedure_keywords:
            if kw in text_lower:
                idx = text_lower.find(kw)
                found.append({
                    "type": "procedure",
                    "value": kw,
                    "confidence": 0.8,
                    "context": text[max(0, idx - 30):idx + len(kw) + 30],
                })

        return self._deduplicate_entities(found)

    def _extract_providers(self, text: str) -> List[Dict]:
        """Extract provider names and NPIs."""
        found = []

        # Provider names with credentials
        provider_pattern = r"(?:Dr\.?|Doctor)\s+([A-Z][a-zA-Z\-]+(?:\s+[A-Z][a-zA-Z\-]+)?)|\b([A-Z][a-zA-Z\-]+(?:\s+[A-Z][a-zA-Z\-]+)?),?\s+(MD|DO|NP|PA|RN|PharmD)\b"
        for match in re.finditer(provider_pattern, text):
            name = match.group(1) or match.group(2)
            cred = match.group(3) or "MD/DO"
            if name and len(name) > 2:
                found.append({
                    "type": "provider",
                    "value": f"{name} ({cred})",
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                    "metadata": {"credential": cred},
                })

        # NPI numbers
        npi_pattern = r"(?:NPI|national provider identifier)[:\s]+(\d{10})"
        for match in re.finditer(npi_pattern, text, re.IGNORECASE):
            found.append({
                "type": "npi",
                "value": match.group(1),
                "confidence": 0.95,
                "context": "",
            })

        return self._deduplicate_entities(found)

    def _extract_facilities(self, text: str) -> List[Dict]:
        """Extract facility names."""
        found = []
        facility_pattern = r"\b([A-Z][A-Za-z0-9\s&\.\-]+(?:Hospital|Clinic|Medical Center|Health System|Lab|Laboratory|Urgent Care|Rehab))\b"
        for match in re.finditer(facility_pattern, text):
            name = match.group(1).strip()
            if len(name) > 3:
                found.append({
                    "type": "facility",
                    "value": name,
                    "confidence": 0.8,
                    "context": text[max(0, match.start() - 30):match.end() + 30],
                })

        return self._deduplicate_entities(found)

    def _extract_document_date(self, text: str) -> Optional[str]:
        """Extract document date if explicitly labeled."""
        patterns = [
            r"(?:date|document date|report date)[:\s]+(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{2,4})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    # ------------------------------------------------------------------
    # CLINICAL METRICS & CALCULATIONS (private)
    # ------------------------------------------------------------------

    def _calculate_clinical_metrics(self, text: str, params: Dict) -> Dict[str, Any]:
        """Calculate clinical metrics from explicit params or extracted values."""
        vitals = self._extract_vitals(text)

        # Weight / height extraction
        weight_kg = params.get("weight_kg")
        height_m = params.get("height_m")
        if weight_kg is None:
            weight_kg = self._extract_weight_kg(vitals, text)
        if height_m is None:
            height_m = self._extract_height_m(vitals, text)

        creatinine = params.get("creatinine") or self._extract_lab_value(text, ["creatinine", "scr"])
        age = params.get("age") or self._extract_age(text)
        gender = params.get("gender") or self._extract_gender(text)

        # Cardiac risk params
        cholesterol = params.get("cholesterol") or self._extract_lab_value(text, ["total cholesterol", "cholesterol"])
        hdl = params.get("hdl") or self._extract_lab_value(text, ["hdl"])
        bp = params.get("bp") or self._extract_bp_systolic(text)
        smoker = params.get("smoker", "smok" in text.lower())
        diabetes = params.get("diabetes", "diabetes" in text.lower())

        # Scores from params or text
        apgar = params.get("apgar")
        gcs = params.get("gcs")

        return {
            "bmi": self._extract_bmi(weight_kg, height_m),
            "egfr": self._extract_egfr(creatinine, age, gender),
            "cardiac_risk": self._extract_cardiac_risk(age, cholesterol, hdl, bp, smoker, diabetes, gender),
            "apgar": self._extract_apgar_score(apgar),
            "glasgow": self._extract_glasgow_coma_score(gcs),
            "wells_score": self._extract_wells_score(text, params),
            "chads2_vasc": self._extract_chads2_vasc_score(text, params),
            "child_pugh": self._extract_child_pugh_score(text, params),
        }

    def _extract_weight_kg(self, vitals: List[Dict], text: str) -> Optional[float]:
        for v in vitals:
            if v["type"] == "weight":
                val = float(re.search(r"\d+(?:\.\d+)?", v["value"]).group(0))
                if "lbs" in v["value"].lower() or "pound" in v["value"].lower():
                    return round(val * 0.453592, 2)
                return val
        return None

    def _extract_height_m(self, vitals: List[Dict], text: str) -> Optional[float]:
        for v in vitals:
            if v["type"] == "height":
                val = float(re.search(r"\d+(?:\.\d+)?", v["value"]).group(0))
                unit = v["value"].lower()
                if "cm" in unit:
                    return round(val / 100, 3)
                if "ft" in unit or "'" in v["value"]:
                    return round(val * 0.3048, 3)
                if "in" in unit:
                    return round(val * 0.0254, 3)
                return val
        return None

    def _extract_lab_value(self, text: str, labels: List[str]) -> Optional[float]:
        label_pattern = "|".join(re.escape(label) for label in labels)
        pattern = rf"(?:{label_pattern})[:\s]+([\-]?\d+(?:\.\d+)?)"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            try:
                return float(match.group(1))
            except ValueError:
                continue
        return None

    def _extract_age(self, text: str) -> Optional[int]:
        patterns = [
            r"\b(\d{1,3})\s*-\s*year\s*-\s*old\b",
            r"\b(\d{1,3})\s*year\s*old\b",
            r"\b(?:age|aged)[:\s]+(\d{1,3})\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    def _extract_gender(self, text: str) -> Optional[str]:
        text_lower = text.lower()
        if re.search(r"\bmale\b|\bman\b|\bhe\b|\bhis\b", text_lower):
            return "male"
        if re.search(r"\bfemale\b|\bwoman\b|\bshe\b|\bher\b", text_lower):
            return "female"
        return None

    def _extract_bp_systolic(self, text: str) -> Optional[int]:
        # Prefer BP-labeled readings to avoid matching dates
        match = re.search(r"(?:BP|blood pressure)[:\s]+(\d{2,3})/(\d{2,3})", text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        # Fallback to any BP-like ratio that looks like a vital sign
        for match in re.finditer(r"\b(\d{2,3})/(\d{2,3})\b", text):
            systolic, diastolic = int(match.group(1)), int(match.group(2))
            if 70 <= systolic <= 250 and 40 <= diastolic <= 160:
                return systolic
        return None

    def _extract_bmi(self, weight_kg: Optional[float], height_m: Optional[float]) -> Dict[str, Any]:
        if weight_kg is None or height_m is None or height_m <= 0:
            return {"name": "bmi", "value": None, "inputs": {"weight_kg": weight_kg, "height_m": height_m}, "error": "Missing weight or height"}
        bmi = weight_kg / (height_m ** 2)
        interpretation = "normal"
        if bmi < 18.5:
            interpretation = "underweight"
        elif bmi < 25:
            interpretation = "normal"
        elif bmi < 30:
            interpretation = "overweight"
        else:
            interpretation = "obese"
        return {"name": "bmi", "value": round(bmi, 2), "inputs": {"weight_kg": weight_kg, "height_m": height_m}, "unit": "kg/m²", "interpretation": interpretation, "confidence": 1.0}

    def _extract_egfr(self, creatinine: Optional[float], age: Optional[int], gender: Optional[str]) -> Dict[str, Any]:
        """eGFR using 2021 CKD-EPI race-free equation."""
        if creatinine is None or age is None or gender is None:
            return {"name": "egfr", "value": None, "inputs": {"creatinine": creatinine, "age": age, "gender": gender}, "error": "Missing creatinine, age, or gender"}
        try:
            female = gender.lower() == "female"
            # 2021 CKD-EPI creatinine equation
            if female:
                kappa = 0.7
                alpha = -0.241
                female_factor = 1.012
            else:
                kappa = 0.9
                alpha = -0.302
                female_factor = 1.0

            min_term = min(creatinine / kappa, 1.0)
            max_term = max(creatinine / kappa, 1.0)
            egfr = 142.0 * (min_term ** alpha) * (max_term ** -1.200) * (0.9938 ** age) * female_factor
            interpretation = "normal"
            if egfr < 60:
                interpretation = "decreased"
            if egfr < 30:
                interpretation = "severe"
            return {"name": "egfr", "value": round(egfr, 2), "inputs": {"creatinine": creatinine, "age": age, "gender": gender}, "unit": "mL/min/1.73m²", "interpretation": interpretation, "confidence": 1.0}
        except Exception as exc:
            return {"name": "egfr", "value": None, "inputs": {"creatinine": creatinine, "age": age, "gender": gender}, "error": str(exc), "error_kind": error_kind(exc)}

    def _extract_cardiac_risk(self, age: Optional[int], cholesterol: Optional[float], hdl: Optional[float], bp: Optional[int], smoker: bool, diabetes: bool, gender: Optional[str]) -> Dict[str, Any]:
        """Point-based Framingham-style 10-year cardiac risk estimate."""
        if age is None or cholesterol is None or hdl is None or bp is None or gender is None:
            return {"name": "cardiac_risk", "value": None, "inputs": {"age": age, "cholesterol": cholesterol, "hdl": hdl, "bp": bp, "smoker": smoker, "diabetes": diabetes, "gender": gender}, "error": "Missing cardiac risk inputs"}
        try:
            points = 0
            # Age points
            if age >= 70:
                points += 5
            elif age >= 60:
                points += 4
            elif age >= 50:
                points += 3
            elif age >= 40:
                points += 2
            else:
                points += 1

            # Gender
            if gender.lower() == "male":
                points += 2

            # Total cholesterol
            if cholesterol >= 280:
                points += 3
            elif cholesterol >= 240:
                points += 2
            elif cholesterol >= 200:
                points += 1

            # HDL
            if hdl < 40:
                points += 2
            elif hdl >= 60:
                points -= 1

            # Systolic BP
            if bp >= 180:
                points += 3
            elif bp >= 160:
                points += 2
            elif bp >= 140:
                points += 1
            elif bp >= 130:
                points += 0.5

            # Smoker
            if smoker:
                points += 2

            # Diabetes
            if diabetes:
                points += 2

            # Map points to approximate 10-year risk
            if points <= 1:
                risk_pct = 2.0
            elif points <= 3:
                risk_pct = 7.0
            elif points <= 6:
                risk_pct = 15.0
            else:
                risk_pct = 25.0 + min(points - 6, 5) * 3.0

            interpretation = "low"
            if risk_pct >= 20:
                interpretation = "high"
            elif risk_pct >= 10:
                interpretation = "intermediate"

            return {"name": "cardiac_risk", "value": round(risk_pct, 2), "inputs": {"age": age, "cholesterol": cholesterol, "hdl": hdl, "bp": bp, "smoker": smoker, "diabetes": diabetes, "gender": gender, "points": points}, "unit": "%", "interpretation": interpretation, "confidence": 0.8}
        except Exception as exc:
            return {"name": "cardiac_risk", "value": None, "inputs": {"age": age, "cholesterol": cholesterol, "hdl": hdl, "bp": bp, "smoker": smoker, "diabetes": diabetes, "gender": gender}, "error": str(exc), "error_kind": error_kind(exc)}

    def _extract_apgar_score(self, apgar: Optional[Any]) -> Dict[str, Any]:
        """APGAR score 0-10."""
        if apgar is not None:
            try:
                score = int(apgar)
                return {"name": "apgar", "value": score, "inputs": {"apgar": apgar}, "interpretation": "normal" if score >= 7 else "low", "confidence": 1.0}
            except (ValueError, TypeError):
                pass
        return {"name": "apgar", "value": None, "inputs": {"apgar": apgar}, "error": "No APGAR provided"}

    def _extract_glasgow_coma_score(self, gcs: Optional[Any]) -> Dict[str, Any]:
        """Glasgow Coma Scale 3-15."""
        if gcs is not None:
            try:
                score = int(gcs)
                interpretation = "severe" if score <= 8 else ("moderate" if score <= 12 else "mild")
                return {"name": "glasgow", "value": score, "inputs": {"gcs": gcs}, "interpretation": interpretation, "confidence": 1.0}
            except (ValueError, TypeError):
                pass
        return {"name": "glasgow", "value": None, "inputs": {"gcs": gcs}, "error": "No GCS provided"}

    def _extract_wells_score(self, text: str, params: Dict) -> Dict[str, Any]:
        """Wells criteria for DVT/PE from text or params."""
        if "wells" in params:
            return {"name": "wells_score", "value": int(params["wells"]), "inputs": {"wells": params["wells"]}, "confidence": 1.0}
        text_lower = text.lower()
        criteria = {
            "clinical signs of dvt": ["clinical signs of dvt", "swelling", "leg swelling"],
            "pe most likely diagnosis": ["pe most likely", "most likely diagnosis"],
            "heart rate > 100": ["heart rate > 100", "tachycardia", "hr > 100"],
            "immobilization": ["immobilization", "surgery within 4 weeks", "recent surgery"],
            "previous dvt/pe": ["previous dvt", "previous pe", "history of dvt"],
            "hemoptysis": ["hemoptysis", "coughing blood"],
            "malignancy": ["malignancy", "cancer", "tumor"],
        }
        score = 0
        found = []
        for criterion, keywords in criteria.items():
            if any(kw in text_lower for kw in keywords):
                score += 1
                found.append(criterion)
        return {"name": "wells_score", "value": score, "inputs": {"criteria_found": found}, "interpretation": "low probability" if score <= 4 else "high probability", "confidence": 0.75 if found else 0.0}

    def _extract_chads2_vasc_score(self, text: str, params: Dict) -> Dict[str, Any]:
        """CHA2DS2-VASc stroke risk score from text or params."""
        if "chads2_vasc" in params:
            return {"name": "chads2_vasc", "value": int(params["chads2_vasc"]), "inputs": {"chads2_vasc": params["chads2_vasc"]}, "confidence": 1.0}
        text_lower = text.lower()
        score = 0
        found = []
        if any(kw in text_lower for kw in ["congestive heart failure", "chf", "heart failure"]):
            score += 1
            found.append("heart_failure")
        if any(kw in text_lower for kw in ["hypertension", "htn"]):
            score += 1
            found.append("hypertension")
        if any(kw in text_lower for kw in ["age 65-74", "aged 65", "aged 66", "aged 67", "aged 68", "aged 69", "aged 70", "aged 71", "aged 72", "aged 73", "aged 74"]):
            score += 1
            found.append("age_65_74")
        # Simplified age >= 75 detection
        age_match = re.search(r"\b(?:age|aged)[:\s]+(\d{1,3})\b", text, re.IGNORECASE)
        if age_match:
            age_val = int(age_match.group(1))
            if age_val >= 75:
                score += 2
                found.append("age_75_plus")
            elif age_val >= 65:
                if "age_65_74" not in found:
                    score += 1
                    found.append("age_65_74")
        if any(kw in text_lower for kw in ["diabetes", "dm"]):
            score += 1
            found.append("diabetes")
        if any(kw in text_lower for kw in ["stroke", "tia", "thromboembolism"]):
            score += 2
            found.append("stroke_tia")
        if any(kw in text_lower for kw in ["vascular disease", "pad", "mi", "myocardial infarction"]):
            score += 1
            found.append("vascular_disease")
        if any(kw in text_lower for kw in ["female", "woman"]):
            score += 1
            found.append("female")
        return {"name": "chads2_vasc", "value": score, "inputs": {"criteria_found": found}, "interpretation": "low" if score == 0 else ("moderate" if score == 1 else "high"), "confidence": 0.75 if found else 0.0}

    def _extract_child_pugh_score(self, text: str, params: Dict) -> Dict[str, Any]:
        """Child-Pugh liver cirrhosis severity from text or params."""
        if "child_pugh" in params:
            return {"name": "child_pugh", "value": int(params["child_pugh"]), "inputs": {"child_pugh": params["child_pugh"]}, "confidence": 1.0}
        # Simplified: count indicators of decompensation / severity
        indicators = ["ascites", "encephalopathy", "varices", "bilirubin", "albumin", "inr", "prolonged pt"]
        text_lower = text.lower()
        found = [kw for kw in indicators if kw in text_lower]
        score = min(15, len(found) * 2)
        interpretation = "A (compensated)" if score <= 6 else ("B (significant)" if score <= 9 else "C (decompensated)")
        return {"name": "child_pugh", "value": score, "inputs": {"indicators_found": found}, "interpretation": interpretation, "confidence": 0.6 if found else 0.0}

    # ------------------------------------------------------------------
    # COMPLIANCE & REGULATORY CHECKING (private)
    # ------------------------------------------------------------------

    def _check_hipaa(self, text: str) -> Dict[str, Any]:
        """Detect HIPAA-related keywords and PHI indicators."""
        text_lower = text.lower()
        keywords = ["phi", "protected health information", "patient privacy", "authorization", "minimum necessary", "covered entity", "business associate"]
        # Also detect PHI presence
        phi_indicators = ["ssn", "mrn", "date of birth", "dob", "phone", "address", "email", "fax"]
        found = [kw for kw in keywords if kw in text_lower]
        phi_found = [kw for kw in phi_indicators if kw in text_lower]
        return {
            "regulation": "hipaa",
            "detected": bool(found) or bool(phi_found),
            "keywords_found": found + phi_found,
            "confidence": round(min(1.0, (len(found) + len(phi_found)) / 4.0), 2) if (found or phi_found) else 0.0,
        }

    def _check_fda_21_cfr(self, text: str) -> Dict[str, Any]:
        """Detect FDA 21 CFR Part 11 concepts."""
        text_lower = text.lower()
        keywords = ["21 cfr part 11", "electronic records", "electronic signature", "audit trail", "part 11", "fda 21 cfr"]
        found = [kw for kw in keywords if kw in text_lower]
        return {
            "regulation": "fda_21_cfr",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 2.0), 2) if found else 0.0,
        }

    def _check_clinical_trial_compliance(self, text: str) -> Dict[str, Any]:
        """Detect clinical trial compliance concepts."""
        text_lower = text.lower()
        keywords = ["good clinical practice", "gcp", "ich e6", "irb approval", "informed consent", "adverse event", "ae reporting", "clinical protocol"]
        found = [kw for kw in keywords if kw in text_lower]
        return {
            "regulation": "clinical_trial",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_gdpr_health(self, text: str) -> Dict[str, Any]:
        """Detect GDPR health data concepts."""
        text_lower = text.lower()
        keywords = ["special category data", "health data processing", "data subject consent", "right to erasure", "gdpr", "data retention"]
        found = [kw for kw in keywords if kw in text_lower]
        return {
            "regulation": "gdpr_health",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_joint_commission(self, text: str) -> Dict[str, Any]:
        """Detect Joint Commission / NPSG concepts."""
        text_lower = text.lower()
        keywords = ["national patient safety goals", "sentinel event", "medication reconciliation", "patient identification", "joint commission", "npsg"]
        found = [kw for kw in keywords if kw in text_lower]
        return {
            "regulation": "joint_commission",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    # ------------------------------------------------------------------
    # RISK SCORING (private)
    # ------------------------------------------------------------------

    def _score_readmission_risk(self, text: str) -> Dict[str, Any]:
        """Score readmission risk."""
        text_lower = text.lower()
        indicators = ["prior admission", "readmit", "comorbidities", "social determinants", "length of stay", "discharge planning"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {
            "category": "readmission",
            "score": round(score, 2),
            "level": self._risk_level(score),
            "indicators": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _score_medication_error_risk(self, text: str) -> Dict[str, Any]:
        """Score medication error risk."""
        text_lower = text.lower()
        indicators = ["look-alike", "sound-alike", "high-alert medication", "dosage range", "medication error", "wrong dose"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {
            "category": "medication_error",
            "score": round(score, 2),
            "level": self._risk_level(score),
            "indicators": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _score_infection_risk(self, text: str) -> Dict[str, Any]:
        """Score infection risk."""
        text_lower = text.lower()
        indicators = ["hai", "mrsa", "c. diff", "catheter days", "surgical site infection", "healthcare associated infection"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {
            "category": "infection",
            "score": round(score, 2),
            "level": self._risk_level(score),
            "indicators": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _score_fall_risk(self, text: str) -> Dict[str, Any]:
        """Score fall risk."""
        text_lower = text.lower()
        indicators = ["morse fall scale", "age > 65", "gait", "sedative", "antihypertensive", "fall risk", "history of falls"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {
            "category": "fall",
            "score": round(score, 2),
            "level": self._risk_level(score),
            "indicators": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _score_mortality_risk(self, text: str) -> Dict[str, Any]:
        """Score mortality risk."""
        text_lower = text.lower()
        indicators = ["sofa score", "apache ii", "sepsis", "organ failure", "icu admission", "mechanical ventilation", "shock"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {
            "category": "mortality",
            "score": round(score, 2),
            "level": self._risk_level(score),
            "indicators": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _compute_overall_risk(self, text: str) -> Dict[str, Any]:
        """Combine individual risk scores into an overall score."""
        readmission = self._score_readmission_risk(text)
        med = self._score_medication_error_risk(text)
        infection = self._score_infection_risk(text)
        fall = self._score_fall_risk(text)
        mortality = self._score_mortality_risk(text)
        avg = (readmission["score"] + med["score"] + infection["score"] + fall["score"] + mortality["score"]) / 5.0
        return {
            "category": "overall_risk",
            "score": round(avg, 2),
            "level": self._risk_level(avg),
            "indicators": readmission["indicators"] + med["indicators"] + infection["indicators"] + fall["indicators"] + mortality["indicators"],
            "confidence": round(min(readmission["confidence"], med["confidence"], infection["confidence"], fall["confidence"], mortality["confidence"]), 2),
        }

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # EMPTY RESULT
    # ------------------------------------------------------------------
