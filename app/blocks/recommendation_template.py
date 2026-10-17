"""Recommendation Block - Data-driven recommendation generation from variance data"""

import json
import os
from typing import Any, Dict, List, Optional
from app.core.universal_base import UniversalBlock


class RecommendationTemplateBlock(UniversalBlock):
    name = "recommendation_template"
    version = "1.0.0"
    description = "Data-driven construction recommendation engine: variance data → severity-ranked recommendations + action items"
    layer = 3
    tags = ["domain", "construction", "recommendations", "analytics", "reporting"]
    requires = []

    default_config = {
        "max_recommendations": 20,
        "include_action_items": True,
        "custom_rules_env": "RECOMMENDATION_RULES_PATH",
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"variance_data": [{"item": "concrete_c30", "variance_pct": 18.5, "cost_impact_usd": 42000}]}',
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "recommendation_text", "type": "text", "label": "Recommendation"},
                {"name": "severity", "type": "text", "label": "Severity"},
                {"name": "action_items", "type": "list", "label": "Actions"},
            ],
        },
        "quick_actions": [
            {"icon": "📋", "label": "Analyze Variances", "prompt": "Generate recommendations from variance data"},
            {"icon": "⚠️", "label": "Critical Only", "prompt": "Show only critical recommendations"},
        ],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self._custom_rules: Dict = {}
        self._load_custom_rules()

    def _load_custom_rules(self):
        env_path = os.environ.get(
            self.config.get("custom_rules_env", "RECOMMENDATION_RULES_PATH") if hasattr(self, "config") else "RECOMMENDATION_RULES_PATH",
            ""
        )
        if env_path and os.path.exists(env_path):
            try:
                with open(env_path) as f:
                    self._custom_rules = json.load(f)
            except Exception:
                pass

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}

        operation = data.get("operation") or params.get("operation", "recommend")

        if operation == "list_rules":
            return self._list_rules()

        variance_data = data.get("variance_data", [])
        if isinstance(variance_data, dict):
            variance_data = [variance_data]

        recommendations = []
        max_recs = int(params.get("max_recommendations", self.config.get("max_recommendations", 20)))

        for item in variance_data:
            rec = self._analyze_item(item, params)
            if rec:
                recommendations.append(rec)

        # Apply custom rules if any exist
        for item in variance_data:
            for rkey, rule in self._custom_rules.items():
                if self._matches(item, rule.get("condition", {})):
                    rec = self._render_custom(rkey, rule, item, params)
                    if rec:
                        recommendations.append(rec)

        # Sort by severity then by absolute cost impact
        severity_order = {"critical": 0, "high": 1, "warning": 2, "medium": 3, "low": 4, "info": 5}
        recommendations.sort(
            key=lambda r: (
                severity_order.get(r.get("severity"), 99),
                -abs(r.get("cost_impact_usd", 0)),
            )
        )
        recommendations = recommendations[:max_recs]

        primary = recommendations[0] if recommendations else {}
        return {
            "status": "success",
            "recommendation_text": primary.get("recommendation_text", "No critical issues found."),
            "severity": primary.get("severity", "info"),
            "action_items": primary.get("action_items", []) if params.get("include_action_items", True) else [],
            "all_recommendations": recommendations,
            "recommendation_count": len(recommendations),
            "rules_applied": list({r.get("rule_key") for r in recommendations}),
        }

    def _analyze_item(self, item: Dict, params: Dict) -> Optional[Dict]:
        """Analyze a single variance item and generate a real data-driven recommendation."""
        variance_pct = float(item.get("variance_pct", 0))
        cost_impact = float(item.get("cost_impact_usd", item.get("cost_impact", 0)))
        delay_days = float(item.get("delay_days", 0))
        test_result = str(item.get("test_result", "")).lower()
        risk_level = str(item.get("risk_level", "")).lower()
        carbon_kg = float(item.get("carbon_kgco2e", item.get("carbon", 0)))

        # Determine category from available fields
        category = "cost"
        if delay_days > 0:
            category = "schedule"
        elif test_result:
            category = "quality"
        elif risk_level:
            category = "safety"
        elif carbon_kg > 0:
            category = "sustainability"

        # Determine severity from actual values
        if category == "cost":
            if abs(variance_pct) > 20:
                severity = "critical"
            elif abs(variance_pct) > 10:
                severity = "high"
            elif abs(variance_pct) > 5:
                severity = "medium"
            else:
                severity = "low"
        elif category == "schedule":
            if delay_days > 30:
                severity = "critical"
            elif delay_days > 14:
                severity = "high"
            else:
                severity = "medium"
        elif category == "quality":
            severity = "critical" if test_result == "fail" else "medium" if test_result == "marginal" else "low"
        elif category == "safety":
            severity = "critical" if risk_level == "critical" else "high" if risk_level == "high" else "medium"
        elif category == "sustainability":
            severity = "medium" if carbon_kg > 10000 else "low"
        else:
            severity = "info"

        if severity in ("low", "info"):
            return None

        direction = "over" if variance_pct > 0 else "under" if variance_pct < 0 else "neutral"
        item_name = item.get("item") or item.get("item_key") or item.get("description", "Unknown")

        # Build contextual action items from the data
        action_items = []
        if category == "cost":
            if direction == "over":
                action_items.append("Request detailed cost breakdown from supplier")
                action_items.append("Check current market index (ENR, MEED)")
                if severity in ("critical", "high"):
                    action_items.append("Re-tender to minimum 3 pre-qualified suppliers")
                    action_items.append("Escalate to Project Director within 24 hours")
            else:
                action_items.append("Confirm material grade matches specification")
                action_items.append("Check if scope items are missing")
                if severity == "critical":
                    action_items.append("Audit contractor's method statement")
        elif category == "schedule":
            action_items.append("Submit Recovery Programme within 7 days")
            action_items.append("Identify Critical Path impact")
            if severity == "critical":
                action_items.append("Add resources / shift to extended hours")
                action_items.append("Assess EOT entitlement")
        elif category == "quality":
            action_items.append("Issue NCR within 24 hours")
            action_items.append("Stop work on affected area")
            action_items.append("Implement corrective action before reinspection")
        elif category == "safety":
            action_items.append("Issue STOP WORK order immediately")
            action_items.append("Report to HSE Manager")
            action_items.append("Conduct incident investigation")
        elif category == "sustainability":
            action_items.append("Consider supplementary cementitious materials (SCM)")
            action_items.append("Evaluate recycled steel content")
            action_items.append("Report in ESG dashboard")

        category_icons = {
            "cost": "💰",
            "schedule": "📅",
            "quality": "✅",
            "safety": "⚠️",
            "sustainability": "🌱",
        }
        icon = category_icons.get(category, "📌")

        # Build recommendation text from real data
        if category == "cost":
            text = f"{severity.upper()}: {item_name} is {abs(variance_pct):.1f}% {direction} benchmark. Estimated impact: {abs(cost_impact):,.0f} USD."
        elif category == "schedule":
            text = f"{severity.upper()} DELAY: {item_name} is {delay_days:.0f} days behind schedule."
        elif category == "quality":
            text = f"QC {severity.upper()}: {item_name} failed inspection. Non-Conformance Report to be raised."
        elif category == "safety":
            text = f"SAFETY {severity.upper()}: {item_name} presents {risk_level} safety risk."
        elif category == "sustainability":
            text = f"HIGH CARBON: {item_name} contributes {carbon_kg:,.0f} kgCO₂e. Review low-carbon alternatives."
        else:
            text = f"{severity.upper()}: {item_name} requires attention."

        return {
            "rule_key": f"auto_{category}_{severity}",
            "recommendation_text": f"{icon} {text}",
            "severity": severity,
            "action_items": action_items,
            "category": category,
            "item": item_name,
            "cost_impact_usd": cost_impact,
            "variance_pct": variance_pct,
        }

    def _matches(self, item: Dict, condition: Dict) -> bool:
        field = condition.get("field", "")
        op = condition.get("op", "eq")
        val = condition.get("value")

        item_val = item.get(field)
        if item_val is None:
            return False

        try:
            if op == "eq":
                return str(item_val).lower() == str(val).lower()
            if op == "gt":
                return float(item_val) > float(val)
            if op == "lt":
                return float(item_val) < float(val)
            if op == "gte":
                return float(item_val) >= float(val)
            if op == "lte":
                return float(item_val) <= float(val)
            if op == "between":
                lo, hi = float(val[0]), float(val[1])
                return lo <= float(item_val) <= hi
            if op == "contains":
                return str(val).lower() in str(item_val).lower()
        except (TypeError, ValueError, IndexError):
            pass
        return False

    def _render_custom(self, rule_key: str, rule: Dict, item: Dict, params: Dict) -> Optional[Dict]:
        try:
            text = rule["template"].format_map(_DefaultDict(item))
        except Exception:
            text = rule["template"]

        category = rule.get("category", "general")
        icon = {"cost": "💰", "schedule": "📅", "quality": "✅", "safety": "⚠️", "sustainability": "🌱"}.get(category, "📌")
        include_actions = params.get("include_action_items", self.config.get("include_action_items", True))

        return {
            "rule_key": rule_key,
            "recommendation_text": f"{icon} {text}",
            "severity": rule.get("severity", "info"),
            "action_items": rule.get("action_items", []) if include_actions else [],
            "category": category,
            "item": item.get("item") or item.get("item_key") or item.get("description", ""),
            "cost_impact_usd": item.get("cost_impact_usd", 0),
            "variance_pct": item.get("variance_pct", 0),
        }

    def _list_rules(self) -> Dict:
        summary = {
            k: {
                "condition": v.get("condition"),
                "severity": v.get("severity"),
                "category": v.get("category", "general"),
                "template_preview": v["template"][:80] + "..." if len(v.get("template", "")) > 80 else v.get("template", ""),
            }
            for k, v in self._custom_rules.items()
        }
        return {
            "status": "success",
            "recommendation_text": "",
            "severity": "info",
            "action_items": [],
            "rule_library": summary,
            "total_rules": len(self._custom_rules),
            "categories": list({v.get("category", "general") for v in self._custom_rules.values()}),
        }


class _DefaultDict(dict):
    """Format-map fallback: returns '' for missing keys."""
    def __missing__(self, key):
        return ""
