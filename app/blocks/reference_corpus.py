"""Reference Corpus — a shared, read-only corpus that can never answer as a tenant's.

A tenant's corpus holds documents about THEIR asset. A reference corpus holds public
documents about other people's: government audits, official post-event reports,
governing-body standards. Both are useful and they must never be confused, because a
figure from another venue's audit presented as this venue's figure is the provenance
failure the whole reasoning layer exists to prevent.

WHAT THIS BLOCK IS NOT. It is not a second isolation mechanism.
``rag_tenant_isolation`` already implements STEP 0 -- a master corpus structurally
removed from the always-on merge and reachable only as a DISCLOSED fallback when the
active project is empty or thin. The reference corpus IS such a corpus, so this block
plans through that same rule rather than inventing a parallel one. What it adds is
the part STEP 0 does not cover: what may be admitted in the first place.

THE ADMISSION GATE. A write is refused unless the document carries every one of
``source_class``, ``publisher``, ``url``, ``sha256``, ``event``, ``edition_year`` and
``licence``. Not because a schema is tidy: an unlabelled document in a shared corpus
is a figure with no provenance that every tenant can reach.

THE LICENCE GATE is the one that matters most. ``licence: tenant_only`` can NEVER
enter the reference corpus, however it is labelled otherwise. The live case is the
SGSA Green Guide: the purchase licence is personal to the individual and allows three
downloads, so it can only ever be tenant-supplied. A block that admitted it would put
one person's licensed copy in front of every tenant.

MIRRORS ARE REFUSED. Scribd, SlideShare and their like are refused by host: the
official URL or the document stays out. A mirror is not a citation -- it is a copy of
unknown fidelity at an address the publisher does not control.

NAMED-ASSET QUERIES NEVER REACH IT. A question about a named venue or asset is
answered from tenant chunks only. The caller declares that it is asking about a named
asset; when the caller says nothing, this block assumes it IS -- reference is opt-in
and fallback-only, so ambiguity resolves toward the tenant's own documents rather
than toward someone else's.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from app.core.universal_base import UniversalBlock

#: Reserved project-id prefix. A reference corpus lives under it and a tenant project
#: may not claim it, or a tenant could write into the shared corpus by naming itself.
REFERENCE_PREFIX = "ref:"

#: Every field a reference document must carry to be admitted. Each one is here
#: because an answer citing this corpus has to be able to say where the figure came
#: from, which edition it belongs to, and that we were allowed to hold it.
REQUIRED_INGEST_FIELDS: Tuple[str, ...] = (
    "source_class", "publisher", "url", "sha256", "event", "edition_year", "licence",
)

#: ``open`` may be shared. ``tenant_only`` may not, ever. Anything else is refused
#: rather than guessed at -- an unrecognised licence is not a permissive one.
LICENCES_ADMITTED = frozenset({"open"})
LICENCES_KNOWN = frozenset({"open", "tenant_only"})

#: Hosts that are not a publisher. A document is cited at the publisher's own
#: address or it is left out.
REFUSED_HOSTS: Tuple[str, ...] = (
    "scribd.com", "slideshare.net", "docslib.org", "studylib.net", "coursehero.com",
    "academia.edu", "vdocuments.net", "dokumen.pub", "yumpu.com",
)

#: A 64-character hex digest. Anything else is not a sha256, and "the file we
#: happened to fetch" is not a document identity.
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.I)


def _envelope(status, result=None, error=None, detail=None) -> Dict[str, Any]:
    return {"block_id": "reference_corpus", "status": status, "result": result,
            "error": error, "detail": detail}


def is_reference_project(project_id: str) -> bool:
    return str(project_id or "").startswith(REFERENCE_PREFIX)


def refused_host(url: str) -> Optional[str]:
    """The refused host this URL sits on, or None.

    Matched on the registered domain rather than a substring, so a legitimate
    publisher whose path happens to mention a mirror is not refused, and a
    subdomain of a mirror still is.
    """
    host = (urlparse(str(url or "")).hostname or "").lower().rstrip(".")
    if not host:
        return None
    for bad in REFUSED_HOSTS:
        if host == bad or host.endswith("." + bad):
            return bad
    return None


def admit(document: Dict[str, Any], *, project_id: str) -> Dict[str, Any]:
    """Whether one document may enter the reference corpus, and why not.

    Returns the reasons rather than a bare boolean: a refusal a caller cannot act on
    just moves the problem. Every reason names the field.
    """
    reasons: List[str] = []
    document = dict(document or {})

    if not is_reference_project(project_id):
        reasons.append(
            f"project_id {project_id!r} is not a reference corpus — it must start "
            f"with {REFERENCE_PREFIX!r}")

    missing = [f for f in REQUIRED_INGEST_FIELDS
               if not str(document.get(f) or "").strip()]
    if missing:
        reasons.append(
            f"missing {', '.join(missing)} — an unlabelled document in a shared corpus "
            f"is a figure with no provenance that every tenant can reach")

    licence = str(document.get("licence") or "").strip().lower()
    if licence and licence not in LICENCES_KNOWN:
        reasons.append(
            f"licence {licence!r} is not one this block recognises "
            f"({', '.join(sorted(LICENCES_KNOWN))}) — an unrecognised licence is not a "
            f"permissive one")
    elif licence and licence not in LICENCES_ADMITTED:
        reasons.append(
            f"licence {licence!r} may not enter a shared corpus. A tenant-only document "
            f"is licensed to one holder — the SGSA Green Guide is licensed personally "
            f"with three downloads — so it can only ever be tenant-supplied")

    host = refused_host(document.get("url"))
    if host:
        reasons.append(
            f"{host} is a mirror, not a publisher — cite the official URL or leave the "
            f"document out")

    digest = str(document.get("sha256") or "").strip()
    if digest and not _SHA256.match(digest):
        reasons.append(
            f"sha256 {digest!r} is not a 64-character hex digest — without one, the "
            f"document we hold is not provably the document we cited")

    year = document.get("edition_year")
    if year is not None and str(year).strip():
        try:
            int(str(year).strip())
        except ValueError:
            reasons.append(f"edition_year {year!r} is not a year, and an edition is how "
                           f"a figure is told apart from the same figure four years later")

    return {"admitted": not reasons, "reasons": reasons}


def plan(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The retrieval plan: which corpora this query may touch, and how labelled.

    Delegates the isolation rule to ``rag_tenant_isolation`` rather than restating
    it: a reference corpus in the always-on merge is the same defect as a master
    corpus in it, and one rule with one test is worth more than two that agree today.
    """
    from app.blocks.rag_tenant_isolation import RagTenantIsolationBlock

    project_id = str(payload.get("project_id") or "").strip()
    if not project_id:
        return _envelope("refused",
                         error="project_id is required — retrieval without tenant scope "
                               "is refused")
    if is_reference_project(project_id):
        return _envelope(
            "refused",
            error=f"{project_id!r} is a reference corpus, not a tenant. A query is asked "
                  f"AS a tenant and may reach the reference corpus as a fallback; it is "
                  f"never asked as the reference corpus itself")

    requested = [str(r).strip() for r in (payload.get("include_reference") or [])
                 if str(r).strip()]
    bad = [r for r in requested if not is_reference_project(r)]
    if bad:
        return _envelope(
            "refused",
            error=f"include_reference must name reference corpora ({REFERENCE_PREFIX}…); "
                  f"got {', '.join(bad)}")

    # Ambiguity resolves toward the tenant's own documents. A caller that does not
    # say whether it is asking about a named asset is treated as if it is: reference
    # is opt-in and fallback-only, so the safe default is the narrower one.
    named_asset = payload.get("named_asset")
    named_asset = True if named_asset is None else bool(named_asset)

    isolation = RagTenantIsolationBlock()._plan({
        "project_id": project_id,
        # Every reference corpus is a master-shaped corpus: fallback only, and
        # structurally out of the always-on merge.
        "master_corpus_id": requested[0] if requested else "",
        "gk_projects": list(payload.get("gk_projects") or []) + requested,
    })
    if isolation.get("status") != "ok":
        return isolation

    reference_permitted = bool(requested) and not named_asset
    return _envelope("ok", {
        "project_id": project_id,
        "tenant_projects": [project_id] + list(isolation["result"]["gk_projects"]),
        "reference_projects": requested,
        "reference_permitted": reference_permitted,
        "reference_is_fallback_only": True,
        "named_asset_query": named_asset,
        "why": (
            "a named-asset query is answered from tenant chunks only — another venue's "
            "audit is not this venue's figure"
            if named_asset else
            "reference corpora may answer as a DISCLOSED fallback when the tenant "
            "corpus is empty or thin for this query"
        ),
        "labels": {"tenant": "corpus=tenant", "reference": "corpus=reference"},
    })


def label_chunks(chunks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Label every chunk by the corpus it came from.

    An unlabelled chunk is the failure mode: it reads as the tenant's own document
    once it is in an answer, and nothing downstream can tell otherwise.
    """
    out: List[Dict[str, Any]] = []
    for chunk in chunks or []:
        item = dict(chunk or {})
        project = str(item.get("project_id") or "")
        item["corpus"] = "reference" if is_reference_project(project) else "tenant"
        out.append(item)
    return out


class ReferenceCorpusBlock(UniversalBlock):
    """A shared, read-only corpus that can never answer as a tenant's own."""

    name = "reference_corpus"
    version = "1.0.0"
    description = (
        "Shared read-only reference corpus under the reserved 'ref:' project prefix. "
        "Admission is refused unless a document carries source_class, publisher, url, "
        "sha256, event, edition_year and licence; a tenant_only licence can NEVER "
        "enter (the SGSA Green Guide is licensed personally, three downloads); mirror "
        "hosts are refused by domain because a mirror is not a citation. Retrieval "
        "plans through rag_tenant_isolation STEP 0 rather than restating it, so a "
        "reference corpus is structurally out of the always-on merge and reachable "
        "only as a disclosed fallback. A named-asset query is answered from tenant "
        "chunks only, and a caller that does not say is treated as if it is."
    )
    layer = 3
    tags = ["rag", "reference-corpus", "retrieval", "provenance", "licensing"]
    requires: list = []

    default_config: Dict[str, Any] = {}

    ui_schema = {
        "input": {"type": "json", "multiline": True, "placeholder": (
            '{"action": "plan", "project_id": "p1", '
            '"include_reference": ["ref:mega_event_history"], "named_asset": false}')},
        "output": {"type": "json", "fields": [
            {"name": "status", "type": "string", "label": "Status"},
            {"name": "result", "type": "json", "label": "Result"},
        ]},
    }

    async def execute(self, input_data, params=None) -> Dict[str, Any]:
        """Delegate to ``process``, as the sibling RAG blocks do.

        Defined rather than inherited on purpose. The inherited ``execute`` wraps
        whatever ``process`` returns in a second envelope, so the registry adapter
        received an envelope whose ``result`` was another envelope — and a
        certification that guts ``process`` would then be measuring a wrapper that
        does not care what ``process`` said.
        """
        return await self.process(input_data, params)

    async def process(self, input_data, params=None) -> Dict[str, Any]:
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action") or "plan").strip().lower()

        if action == "plan":
            return plan(payload)

        if action == "admit":
            document = payload.get("document")
            if not isinstance(document, dict):
                return _envelope("refused", error="document must be a mapping")
            project_id = str(payload.get("project_id") or "").strip()
            verdict = admit(document, project_id=project_id)
            if not verdict["admitted"]:
                return _envelope("refused", result=verdict,
                                 error="; ".join(verdict["reasons"]))
            return _envelope("ok", verdict,
                             detail=f"admitted to {project_id} as "
                                    f"{document.get('source_class')}")

        if action == "label":
            chunks = payload.get("chunks")
            if not isinstance(chunks, list):
                return _envelope("refused", error="chunks must be a list")
            labelled = label_chunks(chunks)
            return _envelope("ok", {
                "chunks": labelled,
                "reference_count": sum(1 for c in labelled if c["corpus"] == "reference"),
                "tenant_count": sum(1 for c in labelled if c["corpus"] == "tenant"),
            })

        return _envelope("refused",
                         error=f"unknown action {action!r} — expected plan, admit or label")
