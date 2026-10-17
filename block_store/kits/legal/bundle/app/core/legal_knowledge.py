"""Legal domain knowledge — rules and custom user rules injection.

Place at: app/core/legal_knowledge.py

Usage:
    from app.core.legal_knowledge import LegalKnowledge
    lk = LegalKnowledge()
    flags = lk.check_compliance_flags(text)
    risks = lk.check_risk_keywords(text)
    custom = lk.check_custom_rules(text)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# DEFAULT DOMAIN CRITICAL RULES
# ---------------------------------------------------------------------------

CRITICAL_RULES: Dict[str, str] = {
    "privilege": "Attorney-client privileged content must not be shared outside counsel.",
    "confidentiality": "Confidential terms must be marked and handled under NDA.",
    "governing_law": "Governing law and jurisdiction must be clearly stated.",
    "limitation_of_liability": "Unlimited liability clauses require senior approval.",
}


# ---------------------------------------------------------------------------
# COMPLIANCE / REGULATORY KEYWORD MAPS
# ---------------------------------------------------------------------------

COMPLIANCE_KEYWORDS = {
    "gdpr": [
        "data processing", "consent", "data transfer", "dpa", "data processing agreement",
        "standard contractual clauses", "scc", "adequacy decision", "gdpr"
    ],
    "ccpa": [
        "consumer rights", "opt-out", "sale of personal information", "service provider",
        "business purpose", "ccpa", "california consumer privacy"
    ],
    "anti_bribery": [
        "fcpa", "uk bribery act", "facilitation payment", "government official",
        "third-party due diligence", "anti-bribery", "anti corruption"
    ],
    "antitrust": [
        "price fixing", "market allocation", "bid rigging", "non-compete",
        "exclusivity", "most favored nation", "mfn", "antitrust"
    ],
    "sanctions": [
        "ofac", "sdn list", "embargo", "blocked person", "export control",
        "restricted party", "sanctions"
    ],
    "securities": [
        "sec filing", "10-k", "10-q", "8-k", "material contract", "insider trading",
        "disclosure obligation", "securities act"
    ],
}


RISK_KEYWORDS = {
    "litigation": [
        "dispute resolution", "arbitration", "jury waiver", "class action waiver",
        "forum selection", "litigation", "lawsuit"
    ],
    "regulatory": [
        "regulated industry", "licensing requirement", "reporting obligation",
        "enforcement exposure", "regulatory investigation", "compliance"
    ],
    "reputational": [
        "public disclosure", "media coverage", "whistleblower", "regulatory investigation",
        "scandal", "reputational harm"
    ],
    "financial": [
        "unlimited liability", "uncapped indemnity", "personal guarantee",
        "onerous payment", "liquidated damages", "penalty"
    ],
    "ip": [
        "unclear ownership", "broad license", "weak confidentiality",
        "open source", "contamination", "assignment", "work for hire"
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

class LegalKnowledge:
    """Single import point for legal domain knowledge."""

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
