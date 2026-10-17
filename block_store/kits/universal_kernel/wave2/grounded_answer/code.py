"""Neutral grounded answerer: retrieve sources, build prompt, call LLM."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.answer_contract import (
    SOURCE_CLASS_KEY,
    AnswerContractViolation,
    apply_answer_contract,
    coverage_line,
    emit_chunk,
    source_class_of,
)
from block_store.kits.universal_kernel.wave2.hybrid_retrieval import hybrid_search
from block_store.kits.universal_kernel.wave2.llm_provider import LLMProvider
from block_store.kits.universal_kernel.wave2.vector_store import VectorStore


@dataclass
class Citation:
    """Neutral citation record."""

    chunk_id: str
    text_snippet: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        classified = source_class_of(self.metadata) or self.metadata.get(SOURCE_CLASS_KEY)
        payload = {
            "chunk_id": self.chunk_id,
            "text_snippet": self.text_snippet,
            "score": self.score,
            "metadata": self.metadata,
            SOURCE_CLASS_KEY: classified,
        }
        return payload


class GroundedAnswerer:
    """Build grounded answers from retrieved chunks and an LLM provider."""

    def __init__(
        self,
        retriever: VectorStore,
        llm_provider: LLMProvider,
        embed_fn: Optional[Any] = None,
    ) -> None:
        self.retriever = retriever
        self.llm_provider = llm_provider
        self.embed_fn = embed_fn

    def answer(
        self,
        tenant_id: str,
        project_id: str,
        question: str,
        top_k: int = 5,
        corpus_total: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Answer a question using retrieved sources and the configured LLM.

        KERNEL_DEFAULTS K2 / K3: every citation carries ``source_class``
        and the payload includes an ``N of M indexed`` line when the
        caller knows the corpus size. A ``does-not-exist`` claim is
        refused unless that coverage is 100%.
        """
        indexed = 0
        if hasattr(self.retriever, "count"):
            try:
                indexed = int(self.retriever.count(tenant_id, project_id))
            except Exception:
                indexed = 0

        def _coverage_line() -> Optional[str]:
            if corpus_total is None:
                return None
            try:
                return coverage_line(indexed, corpus_total)
            except AnswerContractViolation:
                return None

        empty = {
            "answer": "Insufficient sources.",
            "citations": [],
            "honesty": "insufficient_sources",
            "coverage_line": _coverage_line(),
        }
        if not question or not question.strip():
            return empty

        query_vector = self._embed(question)
        retrieval = hybrid_search(
            self.retriever,
            tenant_id,
            project_id,
            question,
            query_vector,
            top_k=top_k,
        )

        if not retrieval["results"]:
            return empty

        citations: List[Citation] = []
        context_lines: List[str] = []
        chunk_payloads: List[Dict[str, Any]] = []
        for idx, result in enumerate(retrieval["results"], start=1):
            chunk = result.chunk
            metadata = dict(chunk.metadata or {})
            raw_chunk = {
                "id": chunk.id,
                "text": chunk.text or "",
                "metadata": metadata,
                SOURCE_CLASS_KEY: source_class_of(metadata),
            }
            try:
                emitted = emit_chunk(raw_chunk)
            except AnswerContractViolation as exc:
                return {
                    "answer": "Insufficient sources.",
                    "citations": [],
                    "honesty": "refused",
                    "reason": str(exc),
                    "coverage_line": _coverage_line(),
                }
            chunk_payloads.append(emitted)
            citation = Citation(
                chunk_id=chunk.id,
                text_snippet=(chunk.text or "")[:400],
                score=result.score,
                metadata=emitted["metadata"],
            )
            citations.append(citation)
            context_lines.append(
                f"[{idx}] source={chunk.id}, {SOURCE_CLASS_KEY}={emitted[SOURCE_CLASS_KEY]}, "
                f"score={result.score:.4f}\n{chunk.text or ''}"
            )

        prompt = self._build_prompt(question, context_lines)
        completion = self.llm_provider.complete(prompt)

        try:
            contracted = apply_answer_contract(
                chunks=chunk_payloads,
                answer_text=completion.text,
                indexed=indexed,
                total=corpus_total,
            )
        except AnswerContractViolation as exc:
            return {
                "answer": "Insufficient sources.",
                "citations": [c.to_dict() for c in citations],
                "honesty": "refused",
                "reason": str(exc),
                "coverage_line": _coverage_line(),
            }

        return {
            "answer": contracted["answer"],
            "citations": [c.to_dict() for c in citations],
            "honesty": "grounded",
            "coverage_line": contracted["coverage_line"],
            "coverage": contracted["coverage"],
            SOURCE_CLASS_KEY + "_rendered": True,
        }

    def _embed(self, text: str) -> List[float]:
        if self.embed_fn is not None:
            return self.embed_fn(text)
        # Minimal deterministic fallback: hash-based unit vector placeholder.
        import hashlib

        dim = 384
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vec = [0.0] * dim
        for i, byte in enumerate(digest):
            idx = (byte + i * 256) % dim
            vec[idx] += (byte / 255.0) * 2 - 1
        norm = sum(x * x for x in vec) ** 0.5
        if norm == 0:
            vec[0] = 1.0
            return vec
        return [x / norm for x in vec]

    @staticmethod
    def _build_prompt(question: str, context_lines: List[str]) -> str:
        context = "\n\n".join(context_lines)
        return (
            "Answer the question using only the provided reference context.\n\n"
            f"Reference context:\n{context}\n\n"
            f"Question: {question}\n\n"
            "Answer:"
        )
