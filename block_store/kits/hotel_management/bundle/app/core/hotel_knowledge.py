"""Hotel management domain knowledge — rules and custom user rules injection.

Place at: app/core/hotel_knowledge.py

Usage:
    from app.core.hotel_knowledge import HotelKnowledge
    hk = HotelKnowledge()
    flags = hk.check_compliance_flags(text)
    risks = hk.check_risk_keywords(text)
    custom = hk.check_custom_rules(text)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# DEFAULT DOMAIN CRITICAL RULES
# ---------------------------------------------------------------------------

CRITICAL_RULES: Dict[str, str] = {
    "pci_card_data": "Payment card data must never be stored unencrypted or with CVV.",
    "gdpr_consent": "Guest consent is required for marketing data processing.",
    "no_show_fee_disclosure": "No-show and cancellation fees must be disclosed at booking.",
    "rate_parity": "Public rates must respect OTA parity agreements.",
}


# ---------------------------------------------------------------------------
# REGULATORY / COMPLIANCE KEYWORD MAPS
# ---------------------------------------------------------------------------

COMPLIANCE_KEYWORDS = {
    "pci_dss": [
        "credit card storage", "cvv", "tokenization", "pci dss",
        "pci compliance", "cardholder data", "encryption", "payment card"
    ],
    "gdpr": [
        "guest data retention", "consent", "right to erasure",
        "data processing", "personal data", "gdpr", "privacy policy"
    ],
    "local_hospitality": [
        "tourism license", "fire safety", "food hygiene", "accessibility",
        "health inspection", "safety certificate", "hotel license"
    ],
    "tax_compliance": [
        "vat", "tourism tax", "city tax", "resort fee", "service charge",
        "tax disclosure", "occupancy tax"
    ],
}


RISK_KEYWORDS = {
    "overbooking": [
        "overbook", "walked guest", "walk in", "relocation", "sold out",
        "oversold", "compensation"
    ],
    "revenue_leakage": [
        "rate discrepancy", "unauthorized discount", "complimentary room",
        "staff abuse", "rate override", "free upgrade"
    ],
    "fraud": [
        "duplicate booking", "fake credit card", "chargeback", "identity fraud",
        "stolen card", "no show fraud"
    ],
    "maintenance": [
        "out of order", "pending repair", "maintenance request",
        "safety hazard", "guest complaint", "broken"
    ],
    "reputation": [
        "review score", "bad review", "complaint", "social media",
        "ota ranking", "tripadvisor", "negative feedback"
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

class HotelKnowledge:
    """Single import point for hotel management domain knowledge."""

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
