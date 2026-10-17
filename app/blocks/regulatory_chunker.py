"""Regulatory Chunker — dual-RAG chunking rules, ported from <private-repo>
``backend/app/<private-repo>/rag/chunking.py`` (L1/L2 + section-aware).

Ported verbatim-in-behavior: free-text token windows (800 tokens, 15%
overlap), regulatory section splitting that never cuts mid-section and
skips TOC stubs, appendix/annex label tracking, and atomic QA pairs
(Q never split from A).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Optional

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "regulatory_chunker", "status": status, "result": result, "error": error, "detail": detail}


CHUNK_TOKENS = 800
CHUNK_OVERLAP_RATIO = 0.15

_SECTION_RE = re.compile(
    r"(?m)^(?:"
    r"(?:Section|SECTION)\s+(\d+(?:\.\d+)*)"
    r"|(Appendix\s+\d+)"
    r"|(Annex(?:-[a-z0-9]+)?)"
    r"|(\d+)\.\s+[A-Z]"
    r")"
)
_TOC_DOTS_RE = re.compile(r"\.{3,}|…")


@dataclass
class TextChunk:
    text: str
    section: Optional[str] = None
    meta: Optional[dict] = None


def _tokenize(text: str) -> List[str]:
    return text.split()


def _detokenize(tokens: List[str]) -> str:
    return " ".join(tokens)


def chunk_free_text(text: str, *, tokens: int = CHUNK_TOKENS, overlap_ratio: float = CHUNK_OVERLAP_RATIO) -> List[str]:
    words = _tokenize(text.strip())
    if not words:
        return []
    if len(words) <= tokens:
        return [_detokenize(words)]
    overlap = max(1, int(tokens * overlap_ratio))
    stride = max(1, tokens - overlap)
    chunks: List[str] = []
    start = 0
    while start < len(words):
        end = min(start + tokens, len(words))
        piece = _detokenize(words[start:end]).strip()
        if piece:
            chunks.append(piece)
        if end >= len(words):
            break
        start += stride
    return chunks


def _is_toc_stub(body: str) -> bool:
    if _TOC_DOTS_RE.search(body):
        return True
    if len(body) < 100 and body.count("\n") <= 3 and not re.search(r"\d+\.\d+", body):
        return True
    return False


def _looks_like_main_guideline_intro(body: str) -> bool:
    head = body.lower()[:500]
    return "section 133" in head or "insurance ordinance" in head


def _label_for_match(doc: str, match: re.Match, *, appendix_prefix: Optional[str]):
    if match.group(2):
        prefix = f"{doc} {match.group(2).strip()}"
        return prefix, prefix
    if match.group(3):
        prefix = f"{doc} {match.group(3).strip()}"
        return prefix, prefix
    num = match.group(1) or match.group(4)
    if appendix_prefix:
        return f"{appendix_prefix} s.{num}", appendix_prefix
    return f"{doc} s.{num}", appendix_prefix


def chunk_regulatory_by_section(text: str, *, doc: str) -> List[TextChunk]:
    text = text.strip()
    if not text:
        return []
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return [TextChunk(text=text, section=f"{doc} s.1", meta={"doc": doc, "section": f"{doc} s.1"})]
    kept = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        is_appendix_marker = bool(match.group(2) or match.group(3))
        if _is_toc_stub(body) and not is_appendix_marker:
            continue
        if not body:
            continue
        kept.append((match, body))
    chunks: List[TextChunk] = []
    appendix_prefix: Optional[str] = None
    for match, body in kept:
        if match.group(3) and _is_toc_stub(body) and match.group(3).lower() == "annex":
            continue
        if match.group(2) and _is_toc_stub(body):
            appendix_prefix = f"{doc} {match.group(2).strip()}"
            continue
        if match.group(3) and _is_toc_stub(body):
            appendix_prefix = f"{doc} {match.group(3).strip()}"
            continue
        num = match.group(1) or match.group(4)
        if num == "1" and _looks_like_main_guideline_intro(body):
            appendix_prefix = None
        section_label, appendix_prefix = _label_for_match(doc, match, appendix_prefix=appendix_prefix)
        if _is_toc_stub(body):
            continue
        chunks.append(TextChunk(text=body, section=section_label, meta={"doc": doc, "section": section_label}))
    if not chunks:
        return [TextChunk(text=text, section=f"{doc} s.1", meta={"doc": doc, "section": f"{doc} s.1"})]
    return chunks


def chunk_qa_atomic(question: str, answer: str, *, doc_id: str) -> TextChunk:
    q = question.strip()
    a = answer.strip()
    return TextChunk(text=f"Q: {q}\nA: {a}", section=doc_id, meta={"unit_type": "qa_pair", "question": q})


class RegulatoryChunkerBlock(UniversalBlock):
    """Dual-RAG chunking ported from <private-repo>: section-aware regulatory
    splitting + free-text windows + atomic QA pairs."""

    name = "regulatory_chunker"
    version = "1.0.0"
    description = (
        "Dual-RAG chunking ported from <private-repo> rag/chunking.py: regulatory "
        "sections never split mid-section (TOC stubs skipped, appendix labels "
        "tracked), free-text 800-token windows with 15% overlap, atomic QA pairs."
    )
    layer = 3
    tags = ["rag", "chunking", "insurance", "regulatory", "<private-repo>"]
    requires = []

    default_config = {"tokens": CHUNK_TOKENS, "overlap_ratio": CHUNK_OVERLAP_RATIO}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "chunk_regulatory", "doc": "guideline-v2", "text": "Section 1 ...\\nSection 2 ..."}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "chunks", "type": "json", "label": "Chunks"}]},
    }

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "chunk_regulatory")).lower()
        try:
            if action in ("chunk_regulatory", "regulatory", "by_section"):
                chunks = chunk_regulatory_by_section(str(payload.get("text", "")), doc=str(payload.get("doc", "doc")))
                return _envelope("ok", {"chunks": [{"text": c.text, "section": c.section, "meta": c.meta} for c in chunks], "count": len(chunks)})
            if action in ("chunk_free_text", "free_text"):
                chunks = chunk_free_text(
                    str(payload.get("text", "")),
                    tokens=int(payload.get("tokens", self.default_config["tokens"])),
                    overlap_ratio=float(payload.get("overlap_ratio", self.default_config["overlap_ratio"])),
                )
                return _envelope("ok", {"chunks": chunks, "count": len(chunks)})
            if action in ("chunk_qa", "qa_atomic"):
                c = chunk_qa_atomic(str(payload.get("question", "")), str(payload.get("answer", "")), doc_id=str(payload.get("doc_id", "qa")))
                return _envelope("ok", {"chunk": {"text": c.text, "section": c.section, "meta": c.meta}})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["chunk_regulatory", "chunk_free_text", "chunk_qa"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
