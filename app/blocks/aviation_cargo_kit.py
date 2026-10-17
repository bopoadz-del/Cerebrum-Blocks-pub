"""Aviation Cargo Kit — read-only cargo-operations intelligence.

Scope (enforced in code):
- READS:  cargo-operations docs in the project corpus (via RAG), query
- WRITES: grounded + cited cargo output
- NEVER:  fabricate domain figures (gate-enforced); never write to external
          ops systems; never cross tenancy.
- RULE:   numeric outputs route through aviation_grounding_gate.
  Cargo weights/dimensions are SAFETY-CRITICAL and get the same hard-gate
  treatment as fuel/fares.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.typed_block import TypedBlock, Schema, ContentType


logger = logging.getLogger(__name__)


class AviationCargoKitBlock(TypedBlock):
    """Read-only cargo-operations intelligence for aviation operators."""

    name = "aviation_cargo_kit"
    version = "1.0.0"
    description = (
        "Read-only cargo intelligence: weights, dimensions, limits, and "
        "handling rules grounded in project documents."
    )
    layer = 3
    tags = ["aviation", "cargo", "domain", "intelligence", "safety"]
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
        "domain": "cargo",
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"query": "What is the max pallet weight?", "project_id": "..."}',
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
            {"icon": "📦", "label": "Cargo lookup", "prompt": "What do the cargo operations documents say?"},
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
        rag_k = int(data.get("rag_k", params.get("rag_k", self.config.get("rag_k", 5))))

        if not query:
            return self._error("Missing query.")
        if not project_id:
            return self._error("Missing project_id (tenancy boundary).")

        try:
            citations = await self._retrieve(query, project_id, k=rag_k)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Cargo retrieval failed for project %s", project_id)
            return self._error(f"Retrieval failed: {exc}")

        try:
            draft = await self._generate_answer(query, citations)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Cargo generation failed for project %s", project_id)
            return self._error(f"Generation failed: {exc}")

        try:
            grounding = await self._ground(query, draft, citations)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Cargo grounding gate failed for project %s", project_id)
            return self._error(f"Grounding gate failed: {exc}")

        verdict = grounding.get("verdict", "block")
        blocked_reason = grounding.get("blocked_reason")
        allowed_response = grounding.get("allowed_response")

        if verdict == "block":
            return {
                "status": "success",
                "domain": self.config.get("domain", "cargo"),
                "verdict": "block",
                "answer": None,
                "citations": citations,
                "grounding": grounding,
                "blocked_reason": blocked_reason or "Blocked by aviation grounding gate.",
                "disclaimers": grounding.get("required_disclaimers", []),
            }

        return {
            "status": "success",
            "domain": self.config.get("domain", "cargo"),
            "verdict": verdict,
            "answer": allowed_response or draft,
            "citations": citations,
            "grounding": grounding,
            "blocked_reason": None,
            "disclaimers": [
                *grounding.get("required_disclaimers", []),
                "Cargo weights and dimensions are safety-critical — verify against operational sources.",
            ],
        }

    def _error(self, message: str) -> Dict:
        return {
            "status": "error",
            "domain": self.config.get("domain", "cargo"),
            "verdict": "block",
            "answer": None,
            "citations": [],
            "grounding": None,
            "blocked_reason": message,
            "disclaimers": [
                "Verify before operational use.",
                "Cargo weights and dimensions are safety-critical.",
            ],
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
            "You are an aviation cargo operations assistant. "
            "Answer ONLY from the retrieved context. "
            "Do not invent weights, dimensions, limits, or handling rules. "
            "Cite sources using [n] notation. "
            "This is read-only intelligence — never modify cargo bookings or load plans."
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
                "query_type": "cargo",
            },
            params={},
        )
