"""Aviation domain knowledge — rules and custom user rules injection."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


CRITICAL_RULES: Dict[str, str] = {
    "critical": "Airworthiness and maintenance compliance must be strictly followed.",
}


COMPLIANCE_KEYWORDS = {
    "easa": [
        "part 21",
        "part 145",
        "part m",
        "part 147",
        "doa",
        "poa",
        "tco",
        "aoc",
        "continuing airworthiness",
    ],
    "faa_part_121": [
        "operations specifications",
        "opspecs",
        "d095",
        "d097",
        "training program",
        "drug testing",
    ],
    "icao_sms": [
        "safety management system",
        "hazard",
        "risk",
        "safety performance",
        "safety assurance",
    ],
    "etops": [
        "extended range",
        "diversion time",
        "alternate",
        "cargo fire suppression",
        "etops maintenance",
    ],
    "carbon_offsetting": [
        "corsia",
        "eu ets",
        "saf",
        "carbon neutral",
        "emissions trading",
        "climate commitment",
    ],
}


RISK_KEYWORDS = {
    "airworthiness_risk": [
        "overdue ad",
        "repetitive finding",
        "deferred maintenance",
        "aging aircraft",
        "corrosion",
    ],
    "operational_risk": [
        "crew fatigue",
        "scheduling pressure",
        "weather minimums",
        "runway excursion",
        "cfit",
    ],
    "maintenance_risk": [
        "unscheduled removal",
        "parts shortage",
        "aog",
        "mro backlog",
        "technician shortage",
    ],
    "financial_risk": [
        "lease default",
        "fuel spike",
        "currency",
        "insurance premium",
        "bankruptcy",
        "repossession",
    ],
    "reputational_risk": [
        "fatal accident",
        "grounding",
        "media scandal",
        "regulatory action",
        "passenger boycott",
    ],
}


def check_custom_rules(text: str, rules: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Apply caller-supplied regex/keyword rules to text."""
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


class AviationKnowledge:
    """Single import point for aviation domain knowledge."""
    def __init__(self, custom_rules: Optional[List[Dict[str, Any]]] = None):
        self.custom_rules = custom_rules or []
    def set_custom_rules(self, rules: List[Dict[str, Any]]) -> None:
        self.custom_rules = rules or []
    def add_custom_rule(self, rule: Dict[str, Any]) -> None:
        self.custom_rules.append(rule)
    def check_custom_rules(self, text: str) -> List[Dict[str, Any]]:
        return check_custom_rules(text, self.custom_rules)
    def check_compliance_flags(self, text: str) -> Dict[str, Dict[str, Any]]:
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
