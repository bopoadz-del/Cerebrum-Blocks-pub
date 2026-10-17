"""RAG Tenant Isolation — structural isolation contract for RAG retrieval,
ported from The_Fork ``app/core/rag/retriever.py`` (STEP 0 isolation).

Ported: the isolation machinery, not the vector store. The master/client
fallback corpus is structurally unreachable from another project's
populated query (it may only surface as a DISCLOSED fallback when the
active project is empty/thin); the always-on general-knowledge merge
never contains the master corpus; and a named-contract query keeps only
that contract's documents — failing closed to empty rather than filling
with another year's contract.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "rag_tenant_isolation", "status": status, "result": result, "error": error, "detail": detail}


_CONTRACT_DOC_ID = re.compile(r"\b(DD|CC|SC)-\d{4}-\d+\b", re.I)


def extract_contract_doc_ids(query: str) -> List[str]:
    return sorted(set(m.group(0).upper() for m in _CONTRACT_DOC_ID.finditer(query or "")))


class RagTenantIsolationBlock(UniversalBlock):
    """Structural tenant isolation for RAG retrieval."""

    name = "rag_tenant_isolation"
    version = "1.0.0"
    description = (
        "RAG tenant isolation ported from The_Fork app/core/rag/retriever.py STEP 0: "
        "the master/client fallback corpus is structurally unreachable from another "
        "project's populated query (disclosed fallback only when the project is "
        "empty/thin); the general-knowledge merge never contains the master corpus; "
        "a named-contract query keeps only that contract's documents, failing closed "
        "to empty rather than filling with another year's contract."
    )
    layer = 3
    tags = ["rag", "tenant-isolation", "retrieval", "the-fork"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "plan", "project_id": "p1", "master_corpus_id": "master", "gk_projects": ["training_material", "master"]}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "plan")).lower()
        try:
            if action == "plan":
                return self._plan(payload)
            if action == "scope_contract":
                query = str(payload.get("query", ""))
                named = extract_contract_doc_ids(query)
                if not named:
                    return _envelope("ok", {"scoped": False, "contract_ids": []})
                docs = payload.get("docs") or []
                kept = [d for d in docs if any(str(d.get("doc_id", "")).upper().startswith(n) or n in str(d.get("doc_id", "")).upper() for n in named)]
                if not kept:
                    # Fail closed: never fill with another year's contract.
                    return _envelope("refused", error="named contract documents not found; refusing to substitute another contract's chunks", detail={"named": named})
                return _envelope("ok", {"scoped": True, "contract_ids": named, "kept": len(kept), "total": len(docs)})
            if action == "fallback":
                project_chunks = int(payload.get("project_chunks", 0))
                if project_chunks > 0:
                    return _envelope("ok", {"fallback": False, "disclosed": False})
                return _envelope("ok", {"fallback": True, "disclosed": True, "note": "master corpus may surface ONLY as a disclosed fallback on an empty project"})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["plan", "scope_contract", "fallback"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    def _plan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        project_id = str(payload.get("project_id", ""))
        if not project_id:
            return _envelope("refused", error="project_id is required — retrieval without tenant scope is refused")
        master = str(payload.get("master_corpus_id", "")).strip()
        gk = [str(p).strip() for p in (payload.get("gk_projects") or []) if str(p).strip()]
        if master and master in gk:
            # STEP 0: the master corpus is structurally removed from the
            # always-on merge, even when a stale config still lists it.
            gk = [p for p in gk if p != master]
            removed = True
        else:
            removed = False
        return _envelope("ok", {
            "project_id": project_id,
            "gk_projects": gk,
            "master_corpus_removed_from_gk": removed,
            "master_corpus_fallback_only": bool(master),
        })
