"""Aviation PSS Kit — read-only booking/passenger service intelligence.

Scope (enforced in code):
- READS:  booking/PSS documents in the project corpus (via RAG), query
- WRITES: structured booking-intelligence output (grounded + cited)
- NEVER:  emit a fare/availability figure that didn't pass the grounding gate;
          never write to booking systems (read-only intelligence, not a
          transaction engine); never cross project tenancy.
- RULE:   all numeric outputs route through aviation_grounding_gate.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.typed_block import TypedBlock, Schema, ContentType


logger = logging.getLogger(__name__)


class AviationPssKitBlock(TypedBlock):
    """Read-only booking and PSS intelligence for aviation operations."""

    name = "aviation_pss_kit"
    version = "1.0.0"
    description = (
        "Read-only passenger service system (PSS) intelligence: fares, "
        "availability, and booking policy grounded in project documents."
    )
    layer = 3
    tags = ["aviation", "pss", "booking", "domain", "intelligence"]
    requires = ["vector_search", "chat", "aviation_grounding_gate"]

    input_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=["query"],
        optional_fields=["project_id", "tenant_id", "user", "rag_k"],
        format_hints={},
    )

    output_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=["status", "domain", "verdict"],
        optional_fields=[
            "answer",
            "citations",
            "grounding",
            "blocked_reason",
            "disclaimers",
        ],
        format_hints={},
    )

    default_config = {
        "rag_k": 5,
        "domain": "pss",
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"query": "What is the business class fare?", "project_id": "..."}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "verdict", "type": "text", "label": "Grounding Verdict"},
                {"name": "answer", "type": "text", "label": "Answer"},
                {"name": "blocked_reason", "type": "text", "label": "Blocked Reason"},
            ],
        },
        "quick_actions": [
            {"icon": "🎫", "label": "Booking intelligence", "prompt": "What does the PSS data say about fares or availability?"},
        ],
    }

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}

        query = data.get("query") or params.get("query")
        project_id = data.get("project_id") or params.get("project_id")
        tenant_id = data.get("tenant_id") or params.get("tenant_id")
        rag_k = int(data.get("rag_k", params.get("rag_k", self.config.get("rag_k", 5))))

        if not query:
            return self._error("Missing query.")
        if not project_id:
            return self._error("Missing project_id (tenancy boundary).")

        # 1. Retrieve relevant chunks from the project corpus.
        try:
            citations = await self._retrieve(query, project_id, k=rag_k)
        except Exception as exc:  # noqa: BLE001
            logger.exception("PSS retrieval failed for project %s", project_id)
            return self._error(f"Retrieval failed: {exc}")

        # 2. Generate a draft answer using the retrieved context.
        try:
            draft = await self._generate_answer(query, citations)
        except Exception as exc:  # noqa: BLE001
            logger.exception("PSS generation failed for project %s", project_id)
            return self._error(f"Generation failed: {exc}")

        # 3. Safety-critical gate: every figure must be grounded.
        try:
            grounding = await self._ground(query, draft, citations)
        except Exception as exc:  # noqa: BLE001
            logger.exception("PSS grounding gate failed for project %s", project_id)
            return self._error(f"Grounding gate failed: {exc}")

        verdict = grounding.get("verdict", "block")
        blocked_reason = grounding.get("blocked_reason")
        allowed_response = grounding.get("allowed_response")

        if verdict == "block":
            return {
                "status": "success",
                "domain": self.config.get("domain", "pss"),
                "verdict": "block",
                "answer": None,
                "citations": citations,
                "grounding": grounding,
                "blocked_reason": blocked_reason or "Blocked by aviation grounding gate.",
                "disclaimers": grounding.get("required_disclaimers", []),
            }

        return {
            "status": "success",
            "domain": self.config.get("domain", "pss"),
            "verdict": verdict,
            "answer": allowed_response or draft,
            "citations": citations,
            "grounding": grounding,
            "blocked_reason": None,
            "disclaimers": grounding.get("required_disclaimers", []),
        }

    def _error(self, message: str) -> Dict:
        return {
            "status": "error",
            "domain": self.config.get("domain", "pss"),
            "verdict": "block",
            "answer": None,
            "citations": [],
            "grounding": None,
            "blocked_reason": message,
            "disclaimers": ["Verify before operational use."],
        }

    # ------------------------------------------------------------------
    # Dependencies
    # ------------------------------------------------------------------

    async def _resolve_block(self, name: str) -> Optional[Any]:
        dep = self.get_dep(name)
        if dep is not None:
            return dep
        if self.hal is not None:
            try:
                return await self.hal.get_block(name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("HAL resolution failed for %s: %s", name, exc)
        return None

    async def _retrieve(self, query: str, project_id: str, k: int) -> List[Dict]:
        vector_search = await self._resolve_block("vector_search")
        if vector_search is None:
            raise RuntimeError("vector_search block is not available.")

        result = await vector_search.process(
            {"query": query},
            params={"operation": "search", "collection": project_id, "n": k},
        )
        if not isinstance(result, dict):
            return []

        # Normalise vector_search output shape.
        results = result.get("results", result.get("result", {}).get("results", []))
        citations = []
        for item in results:
            if isinstance(item, dict):
                citations.append({
                    "text": item.get("text", ""),
                    "doc_id": item.get("id") or item.get("doc_id"),
                    "score": item.get("score", 0.0),
                    "metadata": item.get("metadata", {}),
                })
        return citations

    async def _generate_answer(self, query: str, citations: List[Dict]) -> str:
        chat = await self._resolve_block("chat")
        if chat is None:
            raise RuntimeError("chat block is not available.")

        context_text = "\n\n".join(
            f"[{i}] {c.get('text', '')}" for i, c in enumerate(citations, start=1)
        )
        system_prompt = (
            "You are an aviation booking/PSS intelligence assistant. "
            "Answer ONLY from the retrieved context. "
            "Do not invent fares, availability, or policy details. "
            "Cite sources using [n] notation. "
            "This is read-only intelligence — never issue booking transactions."
        )
        prompt = f"Context:\n{context_text}\n\nQuestion: {query}"

        result = await chat.process(
            {"text": prompt, "system_prompt": system_prompt},
            params={},
        )
        if not isinstance(result, dict):
            return str(result)
        return result.get("text") or result.get("response") or result.get("answer") or str(result)

    async def _ground(
        self, query: str, answer: str, citations: List[Dict]
    ) -> Dict:
        gate = await self._resolve_block("aviation_grounding_gate")
        if gate is None:
            raise RuntimeError("aviation_grounding_gate block is not available.")

        return await gate.process(
            {
                "query": query,
                "answer": answer,
                "citations": citations,
                "query_type": "fare",
            },
            params={},
        )
