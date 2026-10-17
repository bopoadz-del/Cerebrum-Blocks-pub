"""Medical domain knowledge — rules and custom user rules injection.

Place at: app/core/medical_knowledge.py

Usage:
    from app.core.medical_knowledge import MedicalKnowledge
    mk = MedicalKnowledge()
    flags = mk.check_compliance_flags(text)
    risks = mk.check_risk_keywords(text)
    custom = mk.check_custom_rules(text)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# DEFAULT DOMAIN CRITICAL RULES
# ---------------------------------------------------------------------------

CRITICAL_RULES: Dict[str, str] = {
    "phi_redaction": "Patient identifiers must be redacted before sharing outside the care team.",
    "informed_consent": "Procedures require documented informed consent.",
    "high_alert_meds": "High-alert medications require double-check and documentation.",
    "fall_prevention": "Patients >65 or with gait issues require fall precautions.",
}


# ---------------------------------------------------------------------------
# COMPLIANCE / REGULATORY KEYWORD MAPS
# ---------------------------------------------------------------------------

COMPLIANCE_KEYWORDS = {
    "hipaa": [
        "phi", "protected health information", "patient privacy", "authorization",
        "minimum necessary", "covered entity", "business associate", "breach notification"
    ],
    "fda_21_cfr": [
        "21 cfr part 11", "electronic records", "electronic signature", "audit trail",
        "part 11", "fda 21 cfr"
    ],
    "clinical_trial": [
        "good clinical practice", "gcp", "ich e6", "irb approval", "informed consent",
        "adverse event", "ae reporting", "clinical protocol"
    ],
    "gdpr_health": [
        "special category data", "health data processing", "data subject consent",
        "right to erasure", "gdpr", "data retention"
    ],
    "joint_commission": [
        "national patient safety goals", "sentinel event", "medication reconciliation",
        "patient identification", "joint commission", "npsg"
    ],
}


RISK_KEYWORDS = {
    "readmission": [
        "prior admission", "readmit", "comorbidities", "social determinants",
        "length of stay", "discharge planning"
    ],
    "medication_error": [
        "look-alike", "sound-alike", "high-alert medication", "dosage range",
        "medication error", "wrong dose"
    ],
    "infection": [
        "hai", "mrsa", "c. diff", "catheter days", "surgical site infection",
        "healthcare associated infection"
    ],
    "fall": [
        "morse fall scale", "age > 65", "gait", "sedative", "antihypertensive",
        "fall risk", "history of falls"
    ],
    "mortality": [
        "sofa score", "apache ii", "sepsis", "organ failure", "icu admission",
        "mechanical ventilation", "shock"
    ],
}


# ---------------------------------------------------------------------------
# CUSTOM RULES
# ---------------------------------------------------------------------------

def check_custom_rules(text: str, rules: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Apply caller-supplied regex/keyword rules to text.

    Rule shape:
        {
            "id": "my_rule",
            "pattern": "regex string or list of keywords",
            "type": "regex" | "keyword",
            "message": "Optional message on match"
        }
    """
    if not text or not rules:
        return []

    hits: List[Dict[str, Any]] = []
    text_lower = text.lower()

    for rule in rules:
        rule_id = rule.get("id", "unnamed")
        rule_type = rule.get("type", "keyword")
        pattern = rule.get("pattern")
        matched = False
        matches: List[str] = []

        if rule_type == "regex" and isinstance(pattern, str):
            for m in re.finditer(pattern, text, re.IGNORECASE):
                matched = True
                matches.append(m.group(0))
        elif isinstance(pattern, list):
            for kw in pattern:
                if isinstance(kw, str) and kw.lower() in text_lower:
                    matched = True
                    matches.append(kw)
        elif isinstance(pattern, str):
            if pattern.lower() in text_lower:
                matched = True
                matches.append(pattern)

        if matched:
            hits.append({
                "rule_id": rule_id,
                "message": rule.get("message", f"Rule '{rule_id}' matched"),
                "matches": matches[:10],
            })

    return hits


# ---------------------------------------------------------------------------
# MAIN KNOWLEDGE CLASS
# ---------------------------------------------------------------------------

class MedicalKnowledge:
    """Single import point for medical domain knowledge."""

    def __init__(self, custom_rules: Optional[List[Dict[str, Any]]] = None):
        self.custom_rules = custom_rules or []

    def set_custom_rules(self, rules: List[Dict[str, Any]]) -> None:
        """Replace the current custom rule set."""
        self.custom_rules = rules or []

    def add_custom_rule(self, rule: Dict[str, Any]) -> None:
        """Append a single custom rule."""
        self.custom_rules.append(rule)

    def check_custom_rules(self, text: str) -> List[Dict[str, Any]]:
        """Run user-injected custom rules against text."""
        return check_custom_rules(text, self.custom_rules)

    def check_compliance_flags(self, text: str) -> Dict[str, Dict[str, Any]]:
        """Return detected compliance-framework flags."""
        text_lower = text.lower()
        flags: Dict[str, Dict[str, Any]] = {}
        for regulation, keywords in COMPLIANCE_KEYWORDS.items():
            found = [kw for kw in keywords if kw in text_lower]
            flags[regulation] = {
                "detected": bool(found),
                "keywords_found": found,
                "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
            }
        return flags

    def check_risk_keywords(self, text: str) -> Dict[str, Dict[str, Any]]:
        """Return risk-category keyword hits."""
        text_lower = text.lower()
        risks: Dict[str, Dict[str, Any]] = {}
        for category, keywords in RISK_KEYWORDS.items():
            found = [kw for kw in keywords if kw in text_lower]
            risks[category] = {
                "indicators": found,
                "score": min(1.0, len(found) / 3.0),
                "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
            }
        return risks

    def get_critical_rule(self, rule_id: str) -> Optional[str]:
        return CRITICAL_RULES.get(rule_id)

    def list_critical_rules(self) -> List[str]:
        return list(CRITICAL_RULES.keys())
