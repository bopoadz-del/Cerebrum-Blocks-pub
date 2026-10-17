"""Regulatory chunker tests — ported behavior from <private-repo>."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.regulatory_chunker import RegulatoryChunkerBlock, chunk_free_text, chunk_regulatory_by_section


def _run(coro):
    return asyncio.run(coro)


def test_sections_never_split_mid_section():
    body1 = "First section body text that is long enough to matter. " * 6
    body2 = "Second section body text about regulatory compliance. " * 6
    body3 = "Appendix body with substance that matters for labels. " * 6
    text = f"Section 1\n{body1}\nSection 2\n{body2}\nAppendix 1\n{body3}"
    chunks = chunk_regulatory_by_section(text, doc="guideline-v2")
    assert len(chunks) == 3
    assert chunks[0].section == "guideline-v2 s.1"
    assert chunks[1].section == "guideline-v2 s.2"
    assert chunks[2].section.startswith("guideline-v2 Appendix 1")


def test_toc_stub_skipped():
    body2 = "Real body text for section two that is long enough to survive the stub filter. " * 4
    text = f"Section 1\nContents list .................. 2\nSection 2\n{body2}"
    chunks = chunk_regulatory_by_section(text, doc="d")
    assert len(chunks) == 1
    assert "Contents list" not in chunks[0].text


def test_free_text_windows_overlap():
    text = " ".join(f"word{i}" for i in range(2500))
    chunks = chunk_free_text(text, tokens=800, overlap_ratio=0.15)
    assert len(chunks) >= 3
    assert all(len(c.split()) <= 800 for c in chunks)


def test_qa_atomic():
    b = RegulatoryChunkerBlock()
    r = _run(b.process({"action": "chunk_qa", "question": "What is s.133?", "answer": "A guideline.", "doc_id": "qa-1"}))
    assert r["status"] == "ok"
    assert "Q: What is s.133?" in r["result"]["chunk"]["text"]
    assert "A: A guideline." in r["result"]["chunk"]["text"]


def test_unknown_action_refused():
    b = RegulatoryChunkerBlock()
    r = _run(b.process({"action": "nope"}))
    assert r["status"] == "error"
