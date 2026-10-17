#!/usr/bin/env python3
"""Retrieval evaluation: golden (corpus-sighted) vs blind (corpus-blind).

Golden set: for every KB entry, the query is the entry's own title and the
expected result is that entry — the upper bound a corpus-sighted question
set achieves. Blind set: evals/blind_construction_eval.json, authored
without sight of the corpus; scored by keyword coverage in the top-k.

Run:  python scripts/run_retrieval_eval.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.blocks import _knowledge as kb  # noqa: E402

K = 5


def golden_eval() -> dict:
    kb_doc = kb._load_kb()
    raw = kb_doc.get("entries") if isinstance(kb_doc, dict) else kb_doc
    entries = [e for e in (raw or []) if isinstance(e, dict) and e.get("id")]
    hits = 0
    misses = []
    for entry in entries:
        query = str(entry.get("title") or "")
        if not query:
            continue
        results = kb.search_knowledge(query, top_k=K)
        if any(r.get("id") == entry["id"] for r in results):
            hits += 1
        else:
            misses.append(entry["id"])
    total = len(entries)
    return {"hits": hits, "total": total, "hit_at_k": round(hits / total, 3), "misses": misses}


def blind_eval() -> dict:
    spec = json.loads((ROOT / "evals" / "blind_construction_eval.json").read_text(encoding="utf-8"))
    k = int(spec.get("k", K))
    hits = 0
    detail = []
    for q in spec["questions"]:
        results = kb.search_knowledge(q["question"], top_k=k)
        keywords = [w.lower() for w in q["expected_keywords"]]
        # Strict: a single retrieved entry must contain EVERY expected
        # keyword — a bar the eval can actually fail.
        needed = len(keywords)
        hit = False
        for r in results:
            text = f"{r.get('title', '')} {r.get('statement', '')}".lower()
            if sum(1 for w in keywords if w in text) >= needed:
                hit = True
                break
        hits += hit
        detail.append({"id": q["id"], "hit": hit, "top": [r.get("id") for r in results[:3]]})
    total = len(spec["questions"])
    return {"hits": hits, "total": total, "hit_at_k": round(hits / total, 3), "detail": detail}


def main() -> None:
    golden = golden_eval()
    blind = blind_eval()
    print(json.dumps({
        "corpus": "app/knowledge/construction_kb.json",
        "retriever": "kb.search_knowledge (lexical, deterministic, no embedder)",
        "k": K,
        "golden": {k: v for k, v in golden.items() if k != "misses"},
        "golden_misses": golden["misses"],
        "blind": {k: v for k, v in blind.items() if k != "detail"},
        "blind_detail": blind["detail"],
    }, indent=1))


if __name__ == "__main__":
    main()
