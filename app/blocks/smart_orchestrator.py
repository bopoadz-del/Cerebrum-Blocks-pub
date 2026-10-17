"""Smart Orchestrator Block - Semantic action router for construction workflows"""

import re
from typing import Any, Dict, List, Optional, Tuple
from app.core.universal_base import UniversalBlock


# File extension → action
FILE_TYPE_MAP: Dict[str, str] = {
    ".xlsx": "boq_process",
    ".xls":  "boq_process",
    ".csv":  "boq_process",
    ".xer":  "parse_primavera_schedule",
    ".ifc":  "bim_analysis",
    ".dxf":  "drawing_qto",
    ".dwg":  "drawing_qto",
    ".pdf":  "process_document",
    ".jpg":  "qa_qc_inspection",
    ".jpeg": "qa_qc_inspection",
    ".png":  "qa_qc_inspection",
}

# Actions that can run in parallel safely
PARALLEL_GROUPS: Dict[str, List[str]] = {
    "full_analysis": [
        "boq_process", "spec_analyze", "drawing_qto", "parse_primavera_schedule"
    ],
    "cost_suite": [
        "extract_quantities", "estimate_costs", "procurement_list_generator"
    ],
    "compliance_suite": [
        "spec_analyze", "qa_qc_inspection", "safety_compliance_audit"
    ],
    "reporting_suite": [
        "daily_site_report", "progress_tracker", "cash_flow_forecast"
    ],
}


class SmartOrchestratorBlock(UniversalBlock):
    name = "smart_orchestrator"
    version = "1.0.0"
    description = "Construction semantic router: maps user messages to action queues with TF-IDF similarity scoring"
    layer = 2
    tags = ["infrastructure", "construction", "orchestration", "routing", "nlp"]
    requires = []

    default_config = {
        "max_actions": 5,
        "confidence_threshold": 0.15,
    }

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Describe what you need (e.g. 'analyze the BOQ and check specs')...",
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "action_queue", "type": "list", "label": "Action Queue"},
                {"name": "parallel_flag", "type": "boolean", "label": "Run Parallel"},
            ],
        },
        "quick_actions": [
            {"icon": "🔀", "label": "Route Message", "prompt": "What actions should I run for this request?"},
            {"icon": "📋", "label": "List Actions", "prompt": "List all available construction actions"},
        ],
    }

    def __init__(self, hal_block=None, config=None):
        super().__init__(hal_block, config)
        self._skills_block = None

    def wire_skills(self, skills_block):
        """Wire the skills block for hint enrichment."""
        self._skills_block = skills_block

    # Action → keyword corpus (used for TF-IDF vectorization)
    ACTION_CORPUS: Dict[str, str] = {
        "boq_process": "boq bill of quantities quantities sheet cost sheet price list excel csv parse spreadsheet",
        "extract_quantities": "extract quantities take off qto quantity take measure count items quantity extraction",
        "estimate_costs": "estimate cost cost estimate budget pricing price estimate how much costing",
        "tender_bid_analysis": "tender bid proposal quote comparison contractor bid subcontractor",
        "procurement_list_generator": "procurement material list purchase list buy list vendor list supply",
        "procurement_optimizer": "optimize procurement best supplier cheapest optimize cost supplier selection",
        "payment_certificate": "payment cert valuation progress payment invoice certificate interim payment",
        "cash_flow_forecast": "cash flow s-curve payment schedule fund flow financial forecast",
        "spec_analyze": "spec specification material spec grade requirement astm aci saso standard compliance check",
        "process_specification_full": "full specification spec section csi division masterformat spec document",
        "drawing_qto": "drawing dxf dwg floor plan blueprint autocad measure drawing cad",
        "parse_primavera_schedule": "primavera xer p6 schedule gantt programme baseline program",
        "progress_tracker": "progress completion percent complete actual vs planned delay status",
        "resource_histogram": "resource manpower histogram crew labor loading workforce labour",
        "forensic_delay_analysis": "delay analysis eot extension of time delay claim forensic schedule",
        "bim_analysis": "bim ifc revit 3d model building model navisworks digital model",
        "bim_clash_detection": "clash clash detection interference conflict mep conflict collision",
        "bim_extractor": "extract bim ifc quantities bim quantities model quantities element extraction",
        "digital_twin_sync": "digital twin asset data sync model as-built bim twin synchronization",
        "qa_qc_inspection": "qa qc quality inspection test report ncr non-conformance punch list defect",
        "commissioning_checklist": "commissioning handover pre-commissioning startup checklist functional test",
        "process_contract": "contract subcontract agreement terms clause fidic nec legal document",
        "change_order_impact": "change order co variation scope change amendment change management",
        "variation_order_manager": "variation order vo variation management change log vo tracking",
        "claims_builder": "claim dispute loss and expense damages extension of time compensation",
        "rfi_generator": "rfi request for information query clarification design query information",
        "safety_compliance_audit": "safety hse osha risk assessment hazard ppe toolbox site safety",
        "risk_register_auto_populate": "risk register risk log risk matrix risk assessment risk management",
        "carbon_footprint_calculator": "carbon co2 emissions sustainability embodied carbon lca life cycle assessment",
        "esg_sustainability_report": "esg green leed breeam environmental report sustainability report",
        "daily_site_report": "daily report site diary dsr site report daily log construction diary",
        "submittal_log_generator": "submittal transmittal document log material approval shop drawing approval",
        "as_built_deviation_report": "as-built as built deviation red-line record drawing as constructed",
        "warranty_maintenance_schedule": "warranty maintenance service schedule ppm om preventive maintenance",
        "om_manual_generator": "o&m operation manual maintenance manual handover manual operations",
        "value_engineering": "value engineering ve study cost reduction alternative optimization value analysis",
        "sympy_reason": "variance analysis reasoning compare cost benchmark symbolic formula mathematical analysis",
        "process_document": "document pdf report upload analyse file analyze file",
        "intelligent_workflow": "workflow automate chain pipeline multi-step full analysis automated process",
        "health_check": "health status ping alive system check diagnostic",
    }

    # Action → deliverable type (for skill hint lookup)
    ACTION_DELIVERABLE_MAP: Dict[str, str] = {
        "boq_process": "xlsx",
        "extract_quantities": "xlsx",
        "estimate_costs": "xlsx",
        "tender_bid_analysis": "xlsx",
        "procurement_list_generator": "xlsx",
        "procurement_optimizer": "xlsx",
        "payment_certificate": "xlsx",
        "cash_flow_forecast": "xlsx",
        "process_document": "pdf",
        "daily_site_report": "pdf",
        "submittal_log_generator": "pdf",
        "as_built_deviation_report": "pdf",
        "warranty_maintenance_schedule": "pdf",
        "om_manual_generator": "pdf",
        "process_contract": "docx",
        "change_order_impact": "docx",
        "variation_order_manager": "docx",
        "claims_builder": "docx",
        "rfi_generator": "docx",
        "bim_analysis": "ifc-xlsx",
        "bim_extractor": "ifc-xlsx",
        "bim_clash_detection": "pdf",
        "digital_twin_sync": "ifc-xlsx",
        "qa_qc_inspection": "image-pdf",
        "commissioning_checklist": "pdf",
        "spec_analyze": "pdf",
        "process_specification_full": "pdf",
        "drawing_qto": "xlsx",
        "parse_primavera_schedule": "xlsx",
        "progress_tracker": "xlsx",
        "resource_histogram": "xlsx",
        "forensic_delay_analysis": "xlsx",
        "safety_compliance_audit": "pdf",
        "risk_register_auto_populate": "xlsx",
        "carbon_footprint_calculator": "xlsx",
        "esg_sustainability_report": "pdf",
        "value_engineering": "xlsx",
        "sympy_reason": "xlsx",
        "intelligent_workflow": "webapp",
        "health_check": "backend",
    }

    def _build_tfidf_vectors(self) -> Tuple[Dict[str, List[float]], Dict[str, int]]:
        """Build TF-IDF vectors for each action corpus."""
        from math import log

        # Tokenize all corpora
        tokens_by_action: Dict[str, List[str]] = {}
        all_docs: List[List[str]] = []
        for action, corpus in self.ACTION_CORPUS.items():
            tokens = re.findall(r"[a-z]+", corpus.lower())
            tokens_by_action[action] = tokens
            all_docs.append(tokens)

        # Build vocabulary
        vocab: Dict[str, int] = {}
        idx = 0
        for tokens in all_docs:
            for t in tokens:
                if t not in vocab:
                    vocab[t] = idx
                    idx += 1

        # Document frequency
        doc_freq: Dict[str, int] = {}
        for tokens in all_docs:
            seen = set(tokens)
            for t in seen:
                doc_freq[t] = doc_freq.get(t, 0) + 1

        N = len(all_docs)

        # TF-IDF vectors
        vectors: Dict[str, List[float]] = {}
        for action, tokens in tokens_by_action.items():
            vec = [0.0] * len(vocab)
            tf: Dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            for t, count in tf.items():
                if t in vocab:
                    tf_val = count / len(tokens)
                    idf_val = log(N / doc_freq.get(t, 1))
                    vec[vocab[t]] = tf_val * idf_val
            vectors[action] = vec

        return vectors, vocab

    def _cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = sum(a * a for a in vec_a) ** 0.5
        norm_b = sum(b * b for b in vec_b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}

        user_message = (
            data.get("user_message")
            or data.get("message")
            or data.get("text")
            or data.get("input")
            or (input_data if isinstance(input_data, str) else "")
        )
        session_context = data.get("session_context", {})
        file_type = (
            data.get("file_type")
            or params.get("file_type")
            or self._detect_file_type(data, session_context)
        )

        if str(user_message).strip().lower() in ("list actions", "help", "what can you do"):
            return self._list_actions()

        matched = self._match_actions(user_message, file_type)
        max_actions = int(params.get("max_actions", self.config.get("max_actions", 5)))
        action_queue = [m["action"] for m in matched[:max_actions]]

        parallel_group = self._detect_parallel_group(action_queue)
        parallel_flag = parallel_group is not None or len(action_queue) > 1

        if not action_queue:
            return {
                "status": "success",
                "action_queue": [],
                "parallel_flag": False,
                "parallel_group": None,
                "matched_actions": [],
                "file_type_hint": file_type,
                "session_context": session_context,
                "message": "No matching actions found. Provide more details or upload a relevant file.",
            }

        # ── Skill hint enrichment ──────────────────────────────────────────
        skill_hints = {}
        if self._skills_block and action_queue:
            primary_action = action_queue[0]
            deliverable = self.ACTION_DELIVERABLE_MAP.get(primary_action)
            if deliverable:
                try:
                    hints_result = await self._skills_block.execute(
                        deliverable, {"action": "hints", "deliverable": deliverable}
                    )
                    if hints_result.get("status") == "success":
                        skill_hints = {
                            "deliverable": deliverable,
                            "hints": hints_result,
                        }
                    val_result = await self._skills_block.execute(
                        deliverable, {"action": "validation", "deliverable": deliverable}
                    )
                    if val_result.get("status") == "success":
                        skill_hints["validation"] = val_result
                except Exception:
                    pass

        return {
            "status": "success",
            "action_queue": action_queue,
            "parallel_flag": parallel_flag,
            "parallel_group": parallel_group,
            "matched_actions": matched[:max_actions],
            "file_type_hint": file_type,
            "session_context": session_context,
            "skill_hints": skill_hints,
        }

    def _match_actions(self, message: str, file_type: Optional[str]) -> List[Dict]:
        lower_msg = str(message).lower()
        vectors, vocab = self._build_tfidf_vectors()

        # Vectorize user message
        msg_tokens = re.findall(r"[a-z]+", lower_msg)
        msg_vec = [0.0] * len(vocab)
        tf: Dict[str, int] = {}
        for t in msg_tokens:
            tf[t] = tf.get(t, 0) + 1
        for t, count in tf.items():
            if t in vocab:
                msg_vec[vocab[t]] = count / max(len(msg_tokens), 1)

        scores: Dict[str, float] = {}

        # File type gives strong signal
        if file_type and file_type in FILE_TYPE_MAP:
            action = FILE_TYPE_MAP[file_type]
            scores[action] = scores.get(action, 0.0) + 0.8

        # TF-IDF cosine similarity scoring
        for action, vec in vectors.items():
            sim = self._cosine_similarity(msg_vec, vec)
            if sim > 0:
                scores[action] = scores.get(action, 0.0) + sim

        threshold = float(self.config.get("confidence_threshold", 0.15))
        results = [
            {
                "action": action,
                "confidence": round(min(score, 1.0), 3),
            }
            for action, score in sorted(scores.items(), key=lambda x: x[1], reverse=True)
            if score >= threshold
        ]
        return results

    def _detect_file_type(self, data: Dict, context: Dict) -> Optional[str]:
        for key in ("file_path", "filename", "file"):
            val = data.get(key) or context.get(key, "")
            if val:
                ext = "." + str(val).rsplit(".", 1)[-1].lower() if "." in val else ""
                if ext in FILE_TYPE_MAP:
                    return ext
        return None

    def _detect_parallel_group(self, actions: List[str]) -> Optional[str]:
        action_set = set(actions)
        for group_name, group_actions in PARALLEL_GROUPS.items():
            if len(action_set & set(group_actions)) >= 2:
                return group_name
        return None

    def _list_actions(self) -> Dict:
        unique = list(self.ACTION_CORPUS.keys())
        return {
            "status": "success",
            "action_queue": [],
            "parallel_flag": False,
            "all_actions": unique,
            "total_actions": len(unique),
            "parallel_groups": PARALLEL_GROUPS,
            "file_type_routing": FILE_TYPE_MAP,
        }
