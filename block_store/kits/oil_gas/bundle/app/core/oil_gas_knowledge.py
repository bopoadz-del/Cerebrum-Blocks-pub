"""OilGas domain knowledge — rules and custom user rules injection."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


CRITICAL_RULES: Dict[str, str] = {
    "critical": "Well control and environmental protection are critical at all times.",
}


COMPLIANCE_KEYWORDS = {
    "osha": [
        "ppe",
        "hot work",
        "confined space",
        "h2s monitoring",
        "fall protection",
        "bop test",
    ],
    "bsee": [
        "bop",
        "well control",
        "casing",
        "cementing",
        "sems",
        "safety and environmental management system",
    ],
    "epa": [
        "norm",
        "produced water",
        "flaring",
        "methane",
        "ghg",
        "spill prevention",
        "spcc",
    ],
    "phmsa": [
        "pipeline safety",
        "integrity management",
        "im",
        "oq",
        "control room",
        "leak detection",
    ],
    "local_content": [
        "local content requirement",
        "national oil company",
        "psc",
        "royalty",
        "tax",
        "ring-fencing",
    ],
}


RISK_KEYWORDS = {
    "well_control_risk": [
        "kick",
        "blowout",
        "bop failure",
        "cement job",
        "shallow gas",
        "hpht",
        "narrow margin",
    ],
    "environmental_risk": [
        "spill",
        "blowout",
        "flaring",
        "seismic",
        "water contamination",
        "protected area",
        "climate",
    ],
    "regulatory_risk": [
        "permit delay",
        "tax change",
        "noc interference",
        "sanctions",
        "windfall tax",
        "carbon tax",
    ],
    "market_risk": [
        "oil price crash",
        "demand destruction",
        "opec+",
        "energy transition",
        "stranded asset",
    ],
    "operational_risk": [
        "rig failure",
        "supply chain",
        "labor shortage",
        "cyber attack",
        "geopolitical",
        "piracy",
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


class OilGasKnowledge:
    """Single import point for oil_gas domain knowledge."""
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
