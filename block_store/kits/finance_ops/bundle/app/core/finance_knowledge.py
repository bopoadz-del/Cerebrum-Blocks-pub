"""Finance domain knowledge — rules, custom user rules injection, and helpers.

Place at: app/core/finance_knowledge.py

Usage:
    from app.core.finance_knowledge import FinanceKnowledge
    fk = FinanceKnowledge()
    flags = fk.check_custom_rules(text)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# DEFAULT DOMAIN CRITICAL RULES
# ---------------------------------------------------------------------------

CRITICAL_RULES: Dict[str, str] = {
    "material_misstatement": "Any indication of material misstatement must be escalated.",
    "going_concern": "Going concern warnings require explicit disclosure and review.",
    "pep_screening": "Politically exposed persons (PEP) require enhanced due diligence.",
    "str_reporting": "Suspicious transaction reports (STR) must be filed per local AML law.",
}


# ---------------------------------------------------------------------------
# REGULATORY KEYWORD MAPS
# ---------------------------------------------------------------------------

REGULATORY_KEYWORDS = {
    "basel_iii": [
        "capital adequacy", "tier 1 capital", "tier 2 capital",
        "common equity tier 1", "cet1", "leverage ratio",
        "risk weighted assets", " rwa ", "liquidity coverage ratio"
    ],
    "mifid_ii": [
        "best execution", "suitability", "appropriateness",
        "cost disclosure", "mifid", "inducements", "transaction reporting"
    ],
    "sox": [
        "internal controls", "404 certification", "sarbanes oxley",
        "financial reporting accuracy", "icofr", "material weakness"
    ],
    "gdpr": [
        "data processing", "consent", "retention", "right to erasure",
        "data subject", "personal data", "gdpr"
    ],
}


RISK_KEYWORDS = {
    "credit": [
        "credit rating", "default probability", "pd", "exposure at default",
        "ead", "loss given default", "lgd", "impairment", "provision"
    ],
    "market": [
        "volatility", "var", "value at risk", "stress testing",
        "market exposure", "beta", "delta", "gamma"
    ],
    "operational": [
        "process failure", "fraud", "system outage", "operational loss",
        "cyber incident", "breach", "unauthorized transaction"
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

class FinanceKnowledge:
    """Single import point for finance domain knowledge.

    Example:
        fk = FinanceKnowledge()
        flags = fk.check_regulatory_flags(text)
        risks = fk.check_risk_keywords(text)
        custom = fk.check_custom_rules(text, user_rules)
    """

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

    def check_regulatory_flags(self, text: str) -> Dict[str, Dict[str, Any]]:
        """Return detected regulatory-framework flags."""
        text_lower = text.lower()
        flags: Dict[str, Dict[str, Any]] = {}
        for regulation, keywords in REGULATORY_KEYWORDS.items():
            found = [kw for kw in keywords if kw.lower() in text_lower]
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
            found = [kw for kw in keywords if kw.lower() in text_lower]
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
