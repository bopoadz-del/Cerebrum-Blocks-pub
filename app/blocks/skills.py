"""Skills Block — Parse CEREBRUM_SKILL.md and serve hints to the orchestrator."""

import os
import re
from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock


class SkillsBlock(UniversalBlock):
    """Skill knowledge block for Cerebrum agent.

    Parses CEREBRUM_SKILL.md into structured sections and returns
    hints, validation rules, styles, and workflows for a given
    deliverable type or workflow name.

    Actions (via params.action):
        hints       → Relevant hints for a deliverable or workflow
        validation  → Validation rules for a deliverable type
        style       → Style system for a deliverable type
        workflow    → Full workflow pipeline for a domain
        list        → List all deliverable types
        full        → Full skill content for a deliverable type
    """

    name = "skills"
    version = "1.0.0"
    description = (
        "Skill knowledge block — parses CEREBRUM_SKILL.md and serves "
        "hints, validation rules, styles, and workflows to the orchestrator"
    )
    layer = 2
    tags = ["ai", "core", "skills", "knowledge", "orchestrator"]
    requires = []

    default_config = {
        "skill_file": "data/CEREBRUM_SKILL.md",
    }

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Deliverable type or workflow name...",
            "multiline": False,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "hints", "type": "object", "label": "Hints"},
                {"name": "validation", "type": "array", "label": "Validation Rules"},
                {"name": "style", "type": "object", "label": "Style System"},
            ],
        },
        "quick_actions": [
            {"icon": "📚", "label": "Get Hints", "prompt": "Get skill hints for xlsx BOQ"},
            {"icon": "✅", "label": "Validation", "prompt": "Get validation rules for pdf"},
            {"icon": "🎨", "label": "Style", "prompt": "Get style system for xlsx"},
        ],
    }

    # Deliverable matrix extracted from §2
    DELIVERABLE_MAP = {
        "xlsx": {
            "skill_root": "xlsx",
            "primary_tool": "Python + openpyxl/pandas",
            "validation": "6 CLI checks",
            "use_case": "Construction costing, 3-statement models, DCF",
            "section": "4",
        },
        "pdf": {
            "skill_root": "pdf",
            "primary_tool": "HTML + Paged.js / LaTeX (Tectonic)",
            "validation": "Visual + link check",
            "use_case": "Material specs, method statements, QA reports",
            "section": "5",
        },
        "docx": {
            "skill_root": "docx",
            "primary_tool": "C# + OpenXML SDK / python-docx",
            "validation": "Structure check",
            "use_case": "Contracts, design narratives, meeting minutes",
            "section": "6",
        },
        "pptx": {
            "skill_root": "pptx",
            "primary_tool": "PPTD domain language / python-pptx",
            "validation": "Slide verify",
            "use_case": "Investor decks, progress presentations",
            "section": "7",
        },
        "webapp": {
            "skill_root": "webapp-building",
            "primary_tool": "React + TypeScript + Tailwind + shadcn/ui",
            "validation": "Build + lint",
            "use_case": "Internal tools, client portals, progress trackers",
            "section": "8",
        },
        "backend": {
            "skill_root": "backend-building",
            "primary_tool": "FastAPI + PostgreSQL + tRPC/Drizzle",
            "validation": "Test + deploy",
            "use_case": "Cerebrum backend, data ingestion APIs",
            "section": "9",
        },
        "image-pdf": {
            "skill_root": "image-pdf",
            "primary_tool": "PIL + reportlab + OpenCV",
            "validation": "Image integrity",
            "use_case": "Crack detection reports, progress photo logs",
            "section": "5",
        },
        "ifc-xlsx": {
            "skill_root": "ifc-xlsx",
            "primary_tool": "IfcOpenShell + openpyxl",
            "validation": "Schema validate",
            "use_case": "IFC quantity takeoffs, property sets",
            "section": "4",
        },
    }

    WORKFLOW_MAP = {
        "drone_qaqc": {
            "pipeline": [
                "Drone Photos (JPG/RAW)",
                "OpenCV / YOLOv8 (defect detection: cracks, alignment)",
                "Results JSON (defect type, confidence, bbox, image_ref)",
                "PDF Report (reportlab) — photos + annotations + pass/fail",
                "XLSX Log (openpyxl) — defect register with formulas for trend analysis",
                "COMMIT to GitHub → Render serves download link",
            ],
            "blocks": ["image", "pdf", "xlsx"],
            "section": "10.1",
        },
        "bim_boq": {
            "pipeline": [
                "IFC Model",
                "IfcOpenShell (extract quantities: volume, area, count)",
                "Pandas DataFrame (CSI MasterFormat mapping)",
                "XLSX BOQ (openpyxl) — formulas for cost extension",
                "Validate (6 xlsx checks)",
                "COMMIT → Share with QS team",
            ],
            "blocks": ["bim_extractor", "xlsx"],
            "section": "10.2",
        },
        "progress_dashboard": {
            "pipeline": [
                "Site data (daily logs, drone, BIM)",
                "FastAPI ingestion endpoint",
                "PostgreSQL (Render) or SQLite (Jetson local)",
                "React dashboard (Vite + Tailwind)",
                "Docker build → Deploy to Render / Orin",
            ],
            "blocks": ["backend", "webapp"],
            "section": "10.3",
        },
    }

    def __init__(self, hal_block=None, config=None):
        super().__init__(hal_block, config)
        self._raw_content: str = ""
        self._sections: Dict[str, str] = {}
        self._load_skill_file()

    def _skill_path(self) -> str:
        rel = self.config.get("skill_file", "data/CEREBRUM_SKILL.md")
        if os.path.isabs(rel):
            return rel
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        return os.path.join(project_root, rel)

    def _load_skill_file(self):
        path = self._skill_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                self._raw_content = f.read()
        except FileNotFoundError:
            self._raw_content = ""
        self._parse_sections()

    def _parse_sections(self):
        """Split markdown by ## headers into a lookup dict."""
        self._sections = {}
        if not self._raw_content:
            return
        # Match ## headers and capture body until next ## or EOF
        pattern = r"^##\s+(\d+(?:\.\d+)*)?\s*(.*?)\n(.*?)(?=\n##\s+|\Z)"
        matches = re.findall(pattern, self._raw_content, re.MULTILINE | re.DOTALL)
        for num, title, body in matches:
            key = f"{num} {title}".strip() if num else title.strip()
            self._sections[key.lower()] = body.strip()
            # Also index by section number alone
            if num:
                self._sections[num.strip()] = body.strip()

    def _get_section_body(self, section_key: str) -> Optional[str]:
        """Retrieve raw markdown body for a section."""
        # Try exact key first
        body = self._sections.get(section_key.lower())
        if body:
            return body
        # Try fuzzy match on section number prefix (e.g. "4" matches "4.1", "4.2" etc)
        for key, val in self._sections.items():
            if key.startswith(section_key.lower() + " ") or key == section_key.lower():
                return val
        return None

    def _get_hints(self, deliverable: Optional[str], workflow: Optional[str]) -> Dict[str, Any]:
        """Return orchestrator hints for a deliverable or workflow."""
        if workflow and workflow in self.WORKFLOW_MAP:
            wf = self.WORKFLOW_MAP[workflow]
            return {
                "type": "workflow",
                "workflow": workflow,
                "pipeline": wf["pipeline"],
                "recommended_blocks": wf["blocks"],
                "notes": f"See skill section {wf['section']}",
            }

        if not deliverable:
            return {"status": "error", "error": "No deliverable or workflow specified"}

        info = self.DELIVERABLE_MAP.get(deliverable)
        if not info:
            return {"status": "error", "error": f"Unknown deliverable: {deliverable}"}

        # Build hints from the skill file section
        section_body = self._get_section_body(info["section"]) or ""

        # Extract key rules from the section body
        hints = {
            "deliverable": deliverable,
            "skill_root": info["skill_root"],
            "primary_tool": info["primary_tool"],
            "validation_gate": info["validation"],
            "use_case": info["use_case"],
            "key_rules": self._extract_rules(section_body),
            "tech_stack": self._extract_tech_stack(section_body),
        }
        return hints

    def _get_validation(self, deliverable: Optional[str]) -> Dict[str, Any]:
        """Return validation rules for a deliverable type."""
        if not deliverable:
            return {"status": "error", "error": "No deliverable specified"}
        info = self.DELIVERABLE_MAP.get(deliverable)
        if not info:
            return {"status": "error", "error": f"Unknown deliverable: {deliverable}"}

        section_body = self._get_section_body(info["section"]) or ""
        rules = self._extract_validation_rules(section_body)

        # Shared validation layer (§3) always applies
        shared = {
            "pre_flight": [
                "git pull origin main",
                "git status (clean working tree)",
                "python --version >= 3.10+",
                "Core libs present (openpyxl, pandas, reportlab, python-pptx)",
            ],
            "per_artifact_loop": ["PLAN", "CREATE", "SAVE", "CHECK", "FIX", "COMMIT", "NEXT"],
            "post_delivery": [
                "All files committed to GitHub BEFORE sharing",
                "No direct Render shell edits",
                "Every external data point requires citation (Source Name + Source URL)",
            ],
        }

        return {
            "deliverable": deliverable,
            "shared_validation": shared,
            "specific_validation": rules,
        }

    def _get_style(self, deliverable: Optional[str]) -> Dict[str, Any]:
        """Return style system for a deliverable type."""
        if not deliverable:
            return {"status": "error", "error": "No deliverable specified"}
        info = self.DELIVERABLE_MAP.get(deliverable)
        if not info:
            return {"status": "error", "error": f"Unknown deliverable: {deliverable}"}

        section_body = self._get_section_body(info["section"]) or ""
        styles = self._extract_styles(section_body)

        return {
            "deliverable": deliverable,
            "styles": styles,
        }

    def _get_workflow(self, workflow: Optional[str]) -> Dict[str, Any]:
        """Return full workflow pipeline for a domain."""
        if not workflow:
            return {"status": "error", "error": "No workflow specified"}
        wf = self.WORKFLOW_MAP.get(workflow)
        if not wf:
            return {"status": "error", "error": f"Unknown workflow: {workflow}"}

        return {
            "workflow": workflow,
            "pipeline": wf["pipeline"],
            "recommended_blocks": wf["blocks"],
            "skill_section": wf["section"],
        }

    def _list_deliverables(self) -> Dict[str, Any]:
        """List all supported deliverable types."""
        return {
            "deliverables": [
                {"type": k, **v} for k, v in self.DELIVERABLE_MAP.items()
            ],
            "workflows": [
                {"type": k, **v} for k, v in self.WORKFLOW_MAP.items()
            ],
        }

    def _get_full_skill(self, deliverable: Optional[str]) -> Dict[str, Any]:
        """Return full skill content for a deliverable type."""
        if not deliverable:
            return {"status": "error", "error": "No deliverable specified"}
        info = self.DELIVERABLE_MAP.get(deliverable)
        if not info:
            return {"status": "error", "error": f"Unknown deliverable: {deliverable}"}
        body = self._get_section_body(info["section"]) or ""
        return {
            "deliverable": deliverable,
            "skill_root": info["skill_root"],
            "content": body,
        }

    # ── Extraction helpers ──────────────────────────────────────────────────

    @staticmethod
    def _extract_rules(body: str) -> List[str]:
        """Pull bullet-point rules from a section body."""
        rules = []
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("-") or line.startswith("*"):
                rules.append(line.lstrip("-* ").strip())
        return rules[:20]  # Cap to avoid noise

    @staticmethod
    def _extract_tech_stack(body: str) -> List[str]:
        """Extract technology stack lines."""
        stack = []
        in_stack = False
        for line in body.splitlines():
            if "technology stack" in line.lower() or "primary:" in line.lower():
                in_stack = True
            if in_stack and (line.strip().startswith("-") or line.strip().startswith("*")):
                stack.append(line.lstrip("-* ").strip())
            if in_stack and line.strip() == "" and stack:
                break
        return stack

    @staticmethod
    def _extract_validation_rules(body: str) -> List[str]:
        """Extract validation commands/rules from a section."""
        rules = []
        in_validation = False
        for line in body.splitlines():
            lower = line.lower()
            if "validation" in lower or "check" in lower or "verify" in lower:
                in_validation = True
            if in_validation and (line.strip().startswith("-") or line.strip().startswith("*")):
                rules.append(line.lstrip("-* ").strip())
            if in_validation and line.strip().startswith("##"):
                break
        return rules

    @staticmethod
    def _extract_styles(body: str) -> Dict[str, Any]:
        """Extract style systems from a section."""
        styles = {}
        current_key = None
        for line in body.splitlines():
            stripped = line.strip()
            if "style" in stripped.lower() and stripped.endswith(":"):
                current_key = stripped[:-1].strip()
                styles[current_key] = []
            elif current_key and (stripped.startswith("-") or stripped.startswith("*")):
                styles[current_key].append(stripped.lstrip("-* ").strip())
        return styles

    # ── Public process ──────────────────────────────────────────────────────

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        action = params.get("action", "hints")
        deliverable = params.get("deliverable") or (str(input_data) if input_data else None)
        workflow = params.get("workflow")

        if action == "hints":
            result = self._get_hints(deliverable, workflow)
        elif action == "validation":
            result = self._get_validation(deliverable)
        elif action == "style":
            result = self._get_style(deliverable)
        elif action == "workflow":
            result = self._get_workflow(workflow or deliverable)
        elif action == "list":
            result = self._list_deliverables()
        elif action == "full":
            result = self._get_full_skill(deliverable)
        else:
            return {"status": "error", "error": f"Unknown action: {action}. Use hints/validation/style/workflow/list/full"}

        if isinstance(result, dict) and result.get("status") == "error":
            return result
        return {"status": "success", **result}
