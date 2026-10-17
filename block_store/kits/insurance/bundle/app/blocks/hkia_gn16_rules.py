"""HKIA GN16/GL16 deterministic compliance rule checks.

This block is intentionally limited to local rule evaluation. It does not
prepare, transmit, or submit filings to the Hong Kong Insurance Authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.universal_base import UniversalBlock


_RULESET_VERSION = "2026.1-pilot"

_CORPUS_REFERENCES = [
    {
        "id": "hkia-gl16-2026",
        "title": "Guideline on Underwriting Long Term Insurance Business (Other than Class C Business)",
        "issuer": "Hong Kong Insurance Authority",
        "public_pointer": "https://www.ia.org.hk/en/legislative_framework/files/GL16_2026_EN.pdf",
        "usage_note": "Use the official source for authoritative text; this block stores only original summaries and section pointers.",
    },
    {
        "id": "hkia-gn16-qa",
        "title": "Questions and Answers on GN16",
        "issuer": "Hong Kong Insurance Authority",
        "public_pointer": "https://www.ia.org.hk/en/legislative_framework/files/Q&A-gn16.pdf",
        "usage_note": "Reference aid for interpreting selected GN16 controls; not a substitute for legal review.",
    },
]


_DEFAULT_RULESET: Dict[str, Any] = {
    "ruleset_id": "hkia_gn16_ruleset",
    "version": _RULESET_VERSION,
    "framework": "HKIA GN16 / GL16",
    "jurisdiction": "Hong Kong",
    "scope_summary": (
        "Pilot checks for authorized insurers underwriting long term insurance "
        "business other than Class C business. Checks are deterministic keyword "
        "and structured-field controls for first-pass compliance triage."
    ),
    "rules": [
        {
            "rule_id": "GN16-SCOPE-001",
            "title": "Document scope should identify long term non-Class C business",
            "severity": "medium",
            "citation": "HKIA GL16/GN16 sections 1.2 and 3.2",
            "summary": "The compliance record should make clear whether the product is in GL16/GN16 scope.",
            "remediation": "Record product class, long-term business status, and any exclusion rationale before relying on GN16 controls.",
            "applies_when": {"always": True},
            "check": {
                "type": "required_evidence",
                "keyword_groups": [
                    ["long term", "long-term", "life insurance", "whole life", "endowment", "annuity"],
                    ["class c", "non-class c", "other than class c", "not class c", "linked long term"],
                ],
                "field_groups": [
                    ["business_type", "product_class", "line_of_business"],
                    ["class_c_business", "is_class_c", "scope_exclusion"],
                ],
                "missing_message": "Scope evidence is incomplete for long term non-Class C applicability.",
            },
        },
        {
            "rule_id": "GN16-PROD-001",
            "title": "Product design review should address fair treatment factors",
            "severity": "medium",
            "citation": "HKIA GL16/GN16 section 5",
            "summary": "Product design records should address target customers, affordability, risks, distribution channels, charges, and ongoing monitoring.",
            "remediation": "Add a product governance note covering target customers, needs and affordability, key risks, channels, fees, charges, and post-launch monitoring.",
            "applies_when": {
                "text_any": ["product design", "new product", "product launch", "distribution channel", "target customer"],
                "fields_any_true": ["product_launch", "product_design_review_required"],
            },
            "check": {
                "type": "required_evidence",
                "keyword_groups": [
                    ["target customer", "target market", "customer segment"],
                    ["affordability", "needs", "financial circumstances"],
                    ["product risk", "key risk", "risk factor"],
                    ["distribution channel", "online channel", "agency channel", "broker channel"],
                    ["fee", "charge", "surrender penalty"],
                    ["post-launch", "ongoing monitoring", "product monitoring"],
                ],
                "field_groups": [
                    ["target_customer_reviewed", "target_market"],
                    ["affordability_reviewed", "needs_reviewed"],
                    ["risk_reviewed", "key_risks"],
                    ["distribution_channel_reviewed", "distribution_channels"],
                    ["fees_charges_reviewed", "surrender_penalty_reviewed"],
                    ["post_launch_monitoring", "product_monitoring"],
                ],
                "missing_message": "Product design evidence does not cover all GL16 fair-treatment factors.",
            },
        },
        {
            "rule_id": "GN16-DISC-001",
            "title": "Customer disclosures should be clear, bilingual where applicable, and risk complete",
            "severity": "medium",
            "citation": "HKIA GL16/GN16 sections 6 and 8.3",
            "summary": "Materials should evidence key product risks, exclusions, fees or charges, surrender penalties, and cooling-off information.",
            "remediation": "Add or link customer-facing disclosures for risks, exclusions, fees/charges, surrender consequences, and the cooling-off period.",
            "applies_when": {"always": True},
            "check": {
                "type": "required_evidence",
                "keyword_groups": [
                    ["risk", "product risk", "key risk"],
                    ["exclusion", "key exclusion"],
                    ["fee", "charge", "surrender penalty"],
                    ["cooling-off", "cooling off", "cooling-off period", "21 day"],
                    ["plain language", "clear information", "bilingual", "english and chinese"],
                ],
                "field_groups": [
                    ["risks_disclosed", "key_risks"],
                    ["exclusions_disclosed", "key_exclusions"],
                    ["fees_charges_disclosed", "surrender_penalties_disclosed"],
                    ["cooling_off_disclosed"],
                    ["plain_language_reviewed", "bilingual_materials_available"],
                ],
                "missing_message": "Disclosure evidence is missing one or more expected customer information topics.",
            },
        },
        {
            "rule_id": "GN16-SUIT-001",
            "title": "Suitability assessment and FNA evidence should precede recommendation",
            "severity": "high",
            "citation": "HKIA GL16/GN16 section 7 and Annex sales process",
            "summary": "Records should show customer needs, knowledge, priorities, circumstances, and affordability before advice or sale.",
            "remediation": "Complete or attach FNA/suitability evidence before recommendation, including affordability and needs analysis.",
            "applies_when": {"always": True},
            "check": {
                "type": "required_evidence",
                "keyword_groups": [
                    ["financial needs analysis", "fna", "needs analysis", "suitability assessment"],
                    ["knowledge and experience", "customer knowledge", "insurance experience"],
                    ["needs", "priorities", "circumstances"],
                    ["affordability", "ability to afford", "premium payment horizon"],
                ],
                "field_groups": [
                    ["fna_completed", "suitability_assessment_completed"],
                    ["customer_knowledge_recorded", "experience_recorded"],
                    ["needs_recorded", "priorities_recorded", "circumstances_recorded"],
                    ["affordability_assessed", "premium_payment_horizon_assessed"],
                ],
                "missing_message": "Suitability/FNA evidence is incomplete before recommendation or contract conclusion.",
            },
        },
        {
            "rule_id": "GN16-ADVICE-001",
            "title": "Advice records should explain options and recommendation basis",
            "severity": "medium",
            "citation": "HKIA GL16/GN16 section 8",
            "summary": "Where advice is given, records should connect the recommendation to disclosed customer needs and available options.",
            "remediation": "Document the options considered, recommendation rationale, key features, exclusions, and customer acknowledgement.",
            "applies_when": {
                "text_any": ["recommend", "recommended", "advice", "advisor", "agent advised"],
                "fields_any_true": ["advice_given", "recommendation_made"],
            },
            "check": {
                "type": "required_evidence",
                "keyword_groups": [
                    ["option", "alternative", "comparison"],
                    ["recommendation rationale", "basis of recommendation", "reason for recommendation"],
                    ["customer acknowledgement", "customer confirmed", "signed acknowledgement"],
                ],
                "field_groups": [
                    ["options_presented", "alternative_options_presented"],
                    ["recommendation_basis", "recommendation_rationale"],
                    ["customer_acknowledgement", "signed_acknowledgement"],
                ],
                "missing_message": "Advice evidence does not show options, rationale, and customer acknowledgement.",
            },
        },
        {
            "rule_id": "GN16-REM-001",
            "title": "Indemnity or advance commission should not appear as an allowed arrangement",
            "severity": "critical",
            "citation": "HKIA GL16/GN16 section 9.2",
            "summary": "Indemnity commission and standing advance payment arrangements are prohibited; commission should be earned.",
            "remediation": "Remove indemnity or advance commission wording and replace it with earned-basis commission controls.",
            "applies_when": {
                "text_any": ["commission", "remuneration", "intermediary", "agent compensation"],
                "fields_any_true": ["commission_arrangement", "intermediary_remuneration"],
            },
            "check": {
                "type": "prohibited_terms",
                "terms": [
                    "indemnity commission",
                    "advance commission",
                    "advanced commission",
                    "commission advance",
                    "advance payment of commission",
                    "upfront commission loan",
                ],
                "allowed_context_terms": [
                    "prohibited",
                    "not permitted",
                    "banned",
                    "no indemnity commission",
                    "no advance commission",
                    "earned basis only",
                ],
                "missing_message": "Prohibited indemnity or advance commission wording appears without clear negating context.",
            },
        },
        {
            "rule_id": "GN16-CLAW-001",
            "title": "Commission plans should include clawback for fraud, money laundering, and mis-selling",
            "severity": "high",
            "citation": "HKIA GL16/GN16 section 9.3",
            "summary": "Commission controls should allow recovery in proven fraud, money laundering, and mis-selling cases.",
            "remediation": "Add a clawback mechanism that fully recovers commission paid in proven fraud, money-laundering, or mis-selling cases.",
            "applies_when": {
                "text_any": ["commission", "remuneration", "intermediary", "agent compensation", "broker compensation"],
                "fields_any_true": ["commission_arrangement", "intermediary_remuneration"],
            },
            "check": {
                "type": "required_evidence",
                "keyword_groups": [
                    ["clawback", "claw back", "recover commission", "commission recovery"],
                    ["fraud", "fraudulent"],
                    ["money laundering", "aml"],
                    ["mis-selling", "misselling", "mis selling"],
                ],
                "field_groups": [
                    ["clawback_mechanism"],
                    ["fraud_recovery_covered"],
                    ["aml_recovery_covered", "money_laundering_recovery_covered"],
                    ["misselling_recovery_covered", "mis_selling_recovery_covered"],
                ],
                "missing_message": "Commission plan lacks full clawback coverage for fraud, money laundering, or mis-selling.",
            },
        },
        {
            "rule_id": "GN16-CONF-001",
            "title": "Conflicts of interest should be monitored and managed",
            "severity": "medium",
            "citation": "HKIA GL16/GN16 section 10.1 to 10.3",
            "summary": "Records should evidence conflict identification, management, disclosure, and informed consent where relevant.",
            "remediation": "Add conflict-of-interest monitoring, disclosure, and informed-consent evidence for advised sales.",
            "applies_when": {
                "text_any": ["advice", "recommendation", "intermediary", "commission", "conflict"],
                "fields_any_true": ["advice_given", "recommendation_made", "conflict_review_required"],
            },
            "check": {
                "type": "required_evidence",
                "keyword_groups": [
                    ["conflict of interest", "conflicts of interest"],
                    ["disclosure", "disclosed"],
                    ["informed consent", "customer consent"],
                    ["ongoing monitor", "monitoring mechanism", "conflict monitoring"],
                ],
                "field_groups": [
                    ["conflicts_identified", "conflict_review_completed"],
                    ["conflicts_disclosed"],
                    ["informed_consent_obtained"],
                    ["conflict_monitoring"],
                ],
                "missing_message": "Conflict management evidence is incomplete for an advised/intermediated sale.",
            },
        },
        {
            "rule_id": "GN16-ANNUAL-001",
            "title": "Non-guaranteed benefit expectations should have ongoing communication",
            "severity": "medium",
            "citation": "HKIA GL16/GN16 sections 4.2, 4.3, and 10.5",
            "summary": "Policies with non-guaranteed illustrations should evidence ongoing expectation management such as annual statements.",
            "remediation": "Add annual communication controls for non-guaranteed benefits and update illustration assumptions when material changes occur.",
            "applies_when": {
                "text_any": ["non-guaranteed", "nonguaranteed", "illustrated benefit", "standard illustration", "participating policy"],
                "fields_any_true": ["non_guaranteed_benefits", "participating_policy"],
            },
            "check": {
                "type": "required_evidence",
                "keyword_groups": [
                    ["annual statement", "anniversary statement", "annual communication"],
                    ["projection", "illustration update", "assumption update"],
                ],
                "field_groups": [
                    ["annual_statement_provided", "annual_communication"],
                    ["illustration_assumptions_reviewed", "projection_update_control"],
                ],
                "missing_message": "Ongoing communication for non-guaranteed benefits is not evidenced.",
            },
        },
        {
            "rule_id": "GN16-LOAN-001",
            "title": "Policy loan facilities should disclose terms and interest changes",
            "severity": "medium",
            "citation": "HKIA GL16/GN16 section 6.7",
            "summary": "Loan facilities should disclose loan terms, interest rate, automatic loan notifications, rate changes, and statement details.",
            "remediation": "Add policy loan disclosures covering terms, interest rate, automatic loan drawdown notices, rate-change notices, and account statements.",
            "applies_when": {
                "text_any": ["policy loan", "automatic policy loan", "loan facility"],
                "fields_any_true": ["policy_loan_facility", "automatic_policy_loan"],
            },
            "check": {
                "type": "required_evidence",
                "keyword_groups": [
                    ["loan term", "loan terms"],
                    ["interest rate"],
                    ["notification", "notice"],
                    ["account statement", "loan balance"],
                ],
                "field_groups": [
                    ["loan_terms_disclosed"],
                    ["loan_interest_disclosed"],
                    ["loan_notice_control"],
                    ["loan_statement_control"],
                ],
                "missing_message": "Policy loan disclosure evidence is incomplete.",
            },
        },
        {
            "rule_id": "GN16-VULN-001",
            "title": "Vulnerable customers should receive audio-recorded post-sale confirmation calls",
            "severity": "critical",
            "citation": "HKIA GL16/GN16 sections 11.2 and 11.3",
            "summary": "Vulnerable customers require identification and audio-recorded post-sale confirmation calls within the expected control window.",
            "remediation": "Identify vulnerable-customer status and complete an audio-recorded post-sale confirmation call, or record unsuccessful-call letter and email/SMS controls.",
            "applies_when": {
                "text_any": ["vulnerable customer", "age 65", "over 65", "primary education", "no regular income"],
                "fields_any_true": ["vulnerable_customer", "post_sale_call_required"],
                "structured_conditions": [
                    {"field": "customer_age", "operator": ">=", "value": 65},
                    {"field": "education_level", "operator": "in", "value": ["primary", "primary level", "below primary"]},
                    {"field": "regular_income", "operator": "is", "value": False},
                ],
            },
            "check": {
                "type": "required_evidence",
                "keyword_groups": [
                    ["post-sale call", "post sale call", "post-sale confirmation", "confirmation call"],
                    ["audio-recorded", "audio recorded", "call recording", "recorded call"],
                    ["5 working days", "five working days"],
                ],
                "field_groups": [
                    ["post_sale_call_completed", "post_sale_call_attempted", "confirmation_letter_sent"],
                    ["post_sale_call_audio_recorded", "call_recording_id"],
                    ["post_sale_call_within_5_working_days"],
                ],
                "missing_message": "Vulnerable-customer post-sale call evidence is incomplete.",
            },
        },
        {
            "rule_id": "GN16-PSC-001",
            "title": "Post-sale control records should be retained for quality control",
            "severity": "medium",
            "citation": "HKIA GL16/GN16 sections 11.4 and 11.5",
            "summary": "Records should cover call attempts, confirmation letters, email/SMS alerts, control reports, and monitoring of unsuccessful calls.",
            "remediation": "Retain post-sale call records, confirmation letters, email/SMS alerts, control reports, and unsuccessful-call monitoring evidence.",
            "applies_when": {
                "text_any": ["post-sale", "post sale", "confirmation call", "vulnerable customer"],
                "fields_any_true": ["post_sale_call_required", "vulnerable_customer"],
            },
            "check": {
                "type": "required_evidence",
                "keyword_groups": [
                    ["confirmation letter"],
                    ["email", "sms", "text message"],
                    ["control report", "quality control", "qa report"],
                    ["unsuccessful call", "failed call", "call attempt"],
                ],
                "field_groups": [
                    ["confirmation_letter_sent"],
                    ["email_sms_alert_sent"],
                    ["control_report_retained", "qa_report_retained"],
                    ["unsuccessful_call_monitoring", "call_attempts_logged"],
                ],
                "missing_message": "Post-sale control documentation is incomplete.",
            },
        },
    ],
}


class HKIAGN16RulesBlock(UniversalBlock):
    """Deterministic GN16/GL16 compliance checks for insurance pilots."""

    name = "hkia_gn16_rules"
    version = "1.0.0"
    description = "Deterministic HKIA GN16/GL16 rule checks for F6 Layer-1 insurance compliance"
    layer = 1
    tags = ["insurance", "compliance", "hkia", "gn16", "gl16", "rules"]
    requires: List[str] = []

    default_config = {
        "ruleset_version": _RULESET_VERSION,
        "enable_live_filing": False,
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"text": "Paste policy or control evidence...", "customer_age": 68}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "findings", "type": "array", "label": "Findings"},
                {"name": "severity", "type": "string", "label": "Severity"},
                {"name": "rule_id", "type": "string", "label": "Rule ID"},
                {"name": "citation", "type": "string", "label": "Citation"},
                {"name": "remediation", "type": "string", "label": "Remediation"},
            ],
        },
        "quick_actions": [
            {"icon": "check", "label": "Evaluate GN16", "prompt": "Evaluate this document for HKIA GN16/GL16 compliance"},
            {"icon": "list", "label": "List Rules", "prompt": "List HKIA GN16/GL16 pilot rules"},
            {"icon": "package", "label": "Build Audit Package", "prompt": "Build a GN16 audit package for this evidence"},
        ],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Route the requested local operation."""
        params = params or {}
        input_operation = input_data.get("operation") if isinstance(input_data, dict) else None
        operation = params.get("operation") or params.get("action") or input_operation or "evaluate"

        if operation == "evaluate":
            return self._evaluate(input_data, params)
        if operation == "list_rules":
            return self._list_rules()
        if operation == "explain_finding":
            return self._explain_finding(input_data, params)
        if operation == "build_audit_package":
            return self._build_audit_package(input_data, params)

        return {
            "status": "error",
            "operation": operation,
            "error": "Unknown operation. Use: evaluate, list_rules, explain_finding, build_audit_package",
        }

    def _evaluate(self, input_data: Any, params: Dict) -> Dict:
        text, fields = self._extract_payload(input_data, params)
        if not text and not fields:
            return {
                "status": "error",
                "operation": "evaluate",
                "error": "Text or structured fields are required for GN16 evaluation",
            }

        normalized_text = self._normalize_text(text)
        findings: List[Dict[str, Any]] = []
        evaluated_rules: List[str] = []
        skipped_rules: List[str] = []

        for rule in self._rules():
            if not self._rule_applies(rule, normalized_text, fields):
                skipped_rules.append(rule["rule_id"])
                continue

            evaluated_rules.append(rule["rule_id"])
            finding = self._evaluate_rule(rule, normalized_text, fields, len(findings) + 1)
            if finding:
                findings.append(finding)

        return {
            "status": "success",
            "operation": "evaluate",
            "ruleset_id": _DEFAULT_RULESET["ruleset_id"],
            "ruleset_version": _DEFAULT_RULESET["version"],
            "framework": _DEFAULT_RULESET["framework"],
            "scope": _DEFAULT_RULESET["scope_summary"],
            "live_filing_submission": False,
            "submission_note": "Rule checks only; no live HKIA filing submission is performed or supported.",
            "compliant": len(findings) == 0,
            "findings": findings,
            "finding_count": len(findings),
            "finding_count_by_severity": self._count_by_severity(findings),
            "rules_evaluated": evaluated_rules,
            "rules_skipped": skipped_rules,
            "limitations": [
                "Deterministic keyword and structured-field pilot checks only.",
                "Official HKIA materials and qualified compliance review remain authoritative.",
                "The block stores original summaries and pointers, not full regulatory text.",
            ],
        }

    def _list_rules(self) -> Dict[str, Any]:
        return {
            "status": "success",
            "operation": "list_rules",
            "ruleset_id": _DEFAULT_RULESET["ruleset_id"],
            "ruleset_version": _DEFAULT_RULESET["version"],
            "rule_count": len(self._rules()),
            "rules": [
                {
                    "rule_id": rule["rule_id"],
                    "title": rule["title"],
                    "severity": rule["severity"],
                    "citation": rule["citation"],
                    "summary": rule["summary"],
                    "remediation": rule["remediation"],
                    "check_type": rule["check"]["type"],
                }
                for rule in self._rules()
            ],
        }

    def _explain_finding(self, input_data: Any, params: Dict) -> Dict[str, Any]:
        rule_id = params.get("rule_id")
        if isinstance(input_data, dict):
            rule_id = rule_id or input_data.get("rule_id")
            finding = input_data.get("finding")
            if isinstance(finding, dict):
                rule_id = rule_id or finding.get("rule_id")

        if not rule_id:
            return {
                "status": "error",
                "operation": "explain_finding",
                "error": "rule_id is required",
            }

        rule = self._rule_by_id(str(rule_id))
        if rule is None:
            return {
                "status": "error",
                "operation": "explain_finding",
                "error": f"Unknown rule_id: {rule_id}",
            }

        return {
            "status": "success",
            "operation": "explain_finding",
            "rule_id": rule["rule_id"],
            "title": rule["title"],
            "severity": rule["severity"],
            "citation": rule["citation"],
            "summary": rule["summary"],
            "why_it_matters": self._why_it_matters(rule["rule_id"]),
            "remediation": rule["remediation"],
            "check": rule["check"],
        }

    def _build_audit_package(self, input_data: Any, params: Dict) -> Dict[str, Any]:
        evaluation = self._evaluate(input_data, params)
        if evaluation.get("status") == "error":
            return evaluation

        text, fields = self._extract_payload(input_data, params)
        evidence_digest = self._evidence_digest(text, fields)

        return {
            "status": "success",
            "operation": "build_audit_package",
            "package_type": "hkia_gn16_layer1_compliance_audit",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ruleset_id": evaluation["ruleset_id"],
            "ruleset_version": evaluation["ruleset_version"],
            "evidence_digest_sha256": evidence_digest,
            "structured_field_keys": sorted(fields.keys()),
            "live_filing_submission": False,
            "submission_note": "This package is for internal audit triage only and is not an HKIA submission.",
            "corpus_references": _CORPUS_REFERENCES,
            "evaluation": evaluation,
            "audit_trail": {
                "engine": self.name,
                "engine_version": self.version,
                "rule_mode": "deterministic_keyword_and_structured_field",
                "copyright_note": "Contains original summaries and pointers only; consult official HKIA publications for source text.",
            },
        }

    def _evaluate_rule(
        self,
        rule: Dict[str, Any],
        normalized_text: str,
        fields: Dict[str, Any],
        sequence: int,
    ) -> Optional[Dict[str, Any]]:
        check = rule["check"]
        check_type = check["type"]

        if check_type == "prohibited_terms":
            matched_terms = self._prohibited_terms_without_local_negation(
                normalized_text,
                check.get("terms", []),
                check.get("allowed_context_terms", []),
            )
            if matched_terms:
                return self._finding(rule, sequence, matched_terms, [], check["missing_message"], fields)
            return None

        if check_type == "required_evidence":
            missing, matched = self._missing_evidence(check, normalized_text, fields)
            if missing:
                return self._finding(rule, sequence, matched, missing, check["missing_message"], fields)
            return None

        return None

    def _missing_evidence(
        self,
        check: Dict[str, Any],
        normalized_text: str,
        fields: Dict[str, Any],
    ) -> Tuple[List[str], List[str]]:
        missing: List[str] = []
        matched: List[str] = []

        keyword_groups = check.get("keyword_groups", [])
        field_groups = check.get("field_groups", [])
        group_count = max(len(keyword_groups), len(field_groups))

        for index in range(group_count):
            keywords = keyword_groups[index] if index < len(keyword_groups) else []
            field_names = field_groups[index] if index < len(field_groups) else []
            keyword_matches = self._matched_terms(normalized_text, keywords)
            field_matches = self._truthy_fields(fields, field_names)

            if keyword_matches or field_matches:
                matched.extend(keyword_matches)
                matched.extend(field_matches)
            else:
                label_source = keywords or field_names or [f"group_{index + 1}"]
                missing.append(" / ".join(label_source[:3]))

        return missing, sorted(set(matched))

    def _finding(
        self,
        rule: Dict[str, Any],
        sequence: int,
        matched_terms: List[str],
        missing_evidence: List[str],
        message: str,
        fields: Dict[str, Any],
    ) -> Dict[str, Any]:
        structured_evidence = {
            key: fields[key]
            for key in sorted(fields)
            if key in self._rule_field_names(rule)
        }
        return {
            "finding_id": f"{rule['rule_id']}-{sequence:03d}",
            "severity": rule["severity"],
            "rule_id": rule["rule_id"],
            "title": rule["title"],
            "citation": rule["citation"],
            "message": message,
            "evidence": {
                "matched_terms": sorted(set(matched_terms)),
                "missing_evidence": missing_evidence,
                "structured_fields": structured_evidence,
            },
            "remediation": rule["remediation"],
        }

    def _rule_applies(self, rule: Dict[str, Any], normalized_text: str, fields: Dict[str, Any]) -> bool:
        applies = rule.get("applies_when", {})
        if applies.get("always"):
            return True

        if self._matched_terms(normalized_text, applies.get("text_any", [])):
            return True

        if self._truthy_fields(fields, applies.get("fields_any_true", [])):
            return True

        for condition in applies.get("structured_conditions", []):
            if self._condition_matches(condition, fields):
                return True

        return False

    def _condition_matches(self, condition: Dict[str, Any], fields: Dict[str, Any]) -> bool:
        field = condition.get("field")
        if field not in fields:
            return False

        actual = fields.get(field)
        operator = condition.get("operator")
        expected = condition.get("value")

        if operator == ">=":
            try:
                return float(actual) >= float(expected)
            except (TypeError, ValueError):
                return False
        if operator == "in":
            return self._normalize_scalar(actual) in {self._normalize_scalar(item) for item in expected}
        if operator == "is":
            return actual is expected
        if operator == "equals":
            return self._normalize_scalar(actual) == self._normalize_scalar(expected)
        return False

    def _extract_payload(self, input_data: Any, params: Dict) -> Tuple[str, Dict[str, Any]]:
        text_parts: List[str] = []
        fields: Dict[str, Any] = {}

        def ingest_dict(payload: Dict[str, Any]) -> None:
            for text_key in ("text", "document_text", "content", "policy_text", "evidence_text"):
                value = payload.get(text_key)
                if isinstance(value, str):
                    text_parts.append(value)

            documents = payload.get("documents")
            if isinstance(documents, list):
                for document in documents:
                    if isinstance(document, str):
                        text_parts.append(document)
                    elif isinstance(document, dict):
                        for text_key in ("text", "content", "document_text"):
                            if isinstance(document.get(text_key), str):
                                text_parts.append(document[text_key])

            nested_fields = payload.get("fields")
            if isinstance(nested_fields, dict):
                fields.update(nested_fields)

            metadata = payload.get("metadata")
            if isinstance(metadata, dict):
                fields.update(metadata)

            for key, value in payload.items():
                if key not in {
                    "text",
                    "document_text",
                    "content",
                    "policy_text",
                    "evidence_text",
                    "documents",
                    "fields",
                    "metadata",
                    "operation",
                    "action",
                }:
                    fields[key] = value

        if isinstance(input_data, str):
            text_parts.append(input_data)
        elif isinstance(input_data, dict):
            ingest_dict(input_data)
        elif input_data is not None:
            text_parts.append(str(input_data))

        if isinstance(params.get("text"), str):
            text_parts.append(params["text"])
        if isinstance(params.get("fields"), dict):
            fields.update(params["fields"])
        if isinstance(params.get("structured_fields"), dict):
            fields.update(params["structured_fields"])

        return "\n".join(part for part in text_parts if part), fields

    def _matched_terms(self, normalized_text: str, terms: List[str]) -> List[str]:
        matches: List[str] = []
        for term in terms:
            if self._term_in_text(normalized_text, term):
                matches.append(term)
        return matches

    def _prohibited_terms_without_local_negation(
        self,
        normalized_text: str,
        terms: List[str],
        allowed_context_terms: List[str],
        window: int = 80,
    ) -> List[str]:
        """Return prohibited terms that lack negating context near the match.

        Document-wide negation must not suppress an unrelated prohibited phrase.
        """
        flagged: List[str] = []
        for term in terms:
            for match in self._term_matches(normalized_text, term):
                start = max(0, match.start() - window)
                end = min(len(normalized_text), match.end() + window)
                local_window = normalized_text[start:end]
                if not self._matched_terms(local_window, allowed_context_terms):
                    flagged.append(term)
                    break
        return flagged

    def _evidence_digest(self, text: str, fields: Dict[str, Any]) -> str:
        payload = {
            "text": self._normalize_text(text),
            "fields": self._canonical_fields(fields),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _canonical_fields(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        return {key: fields[key] for key in sorted(fields)}

    def _term_in_text(self, normalized_text: str, term: str) -> bool:
        return any(True for _ in self._term_matches(normalized_text, term))

    def _term_matches(self, normalized_text: str, term: str):
        normalized_term = self._normalize_text(term)
        if not normalized_term:
            return iter(())
        pattern = r"(?<![a-z0-9])" + re.escape(normalized_term) + r"(?![a-z0-9])"
        return re.finditer(pattern, normalized_text)

    def _truthy_fields(self, fields: Dict[str, Any], field_names: List[str]) -> List[str]:
        matches: List[str] = []
        for field_name in field_names:
            if field_name in fields and self._is_truthy(fields[field_name]):
                matches.append(field_name)
        return matches

    def _is_truthy(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() not in {"", "false", "no", "n/a", "none", "unknown"}
        if isinstance(value, (list, tuple, set, dict)):
            return len(value) > 0
        return True

    def _rules(self) -> List[Dict[str, Any]]:
        return list(_DEFAULT_RULESET["rules"])

    def _rule_by_id(self, rule_id: str) -> Optional[Dict[str, Any]]:
        normalized = rule_id.strip().upper()
        for rule in self._rules():
            if rule["rule_id"].upper() == normalized:
                return rule
        return None

    def _rule_field_names(self, rule: Dict[str, Any]) -> set:
        field_names = set(rule.get("applies_when", {}).get("fields_any_true", []))
        for condition in rule.get("applies_when", {}).get("structured_conditions", []):
            if "field" in condition:
                field_names.add(condition["field"])
        for group in rule.get("check", {}).get("field_groups", []):
            field_names.update(group)
        return field_names

    def _count_by_severity(self, findings: List[Dict[str, Any]]) -> Dict[str, int]:
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for finding in findings:
            severity = finding.get("severity", "info")
            counts[severity] = counts.get(severity, 0) + 1
        return counts

    def _why_it_matters(self, rule_id: str) -> str:
        explanations = {
            "GN16-SCOPE-001": "Scope errors can cause teams to apply an incomplete control set or miss exclusions.",
            "GN16-PROD-001": "Product governance evidence supports fair treatment before the product reaches customers.",
            "GN16-DISC-001": "Clear disclosures help customers understand material risks and contractual consequences.",
            "GN16-SUIT-001": "Suitability evidence links the sale to customer needs and affordability before commitment.",
            "GN16-ADVICE-001": "Advice records make the recommendation auditable and easier to challenge-test.",
            "GN16-REM-001": "Commission structures can create selling incentives that conflict with customer interests.",
            "GN16-CLAW-001": "Clawback terms deter and remediate serious misconduct after commission has been paid.",
            "GN16-CONF-001": "Conflict controls reduce the risk that remuneration or relationships distort advice.",
            "GN16-ANNUAL-001": "Ongoing updates help manage expectations for illustrated non-guaranteed benefits.",
            "GN16-LOAN-001": "Loan disclosures reduce surprise interest, drawdown, and balance risks for policyholders.",
            "GN16-VULN-001": "Vulnerable-customer controls add confirmation that the customer understands rights and obligations.",
            "GN16-PSC-001": "Post-sale records let quality assurance teams monitor control effectiveness and outliers.",
        }
        return explanations.get(rule_id, "This rule supports first-pass GN16/GL16 control evidence review.")

    def _normalize_scalar(self, value: Any) -> str:
        return self._normalize_text(str(value))

    def _normalize_text(self, text: str) -> str:
        lowered = text.lower()
        lowered = lowered.replace("\u2010", "-").replace("\u2011", "-").replace("\u2012", "-")
        lowered = lowered.replace("\u2013", "-").replace("\u2014", "-").replace("\u2019", "'")
        return re.sub(r"\s+", " ", lowered).strip()

