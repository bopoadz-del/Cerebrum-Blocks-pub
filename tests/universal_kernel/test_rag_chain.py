"""End-to-end integration test for the Wave 2 RAG chain."""

import json

import pytest

from block_store.kits.universal_kernel.wave1.audit_evidence import (
    record,
    reset_audit_log,
)
from block_store.kits.universal_kernel.wave1.audit_evidence.code import _default_log
from block_store.kits.universal_kernel.wave2.document_parsing import parse
from block_store.kits.universal_kernel.wave2.embedding_provider import (
    EMBEDDING_DIMENSION,
    get_provider,
)
from block_store.kits.universal_kernel.wave2.grounded_answer import GroundedAnswerer
from block_store.kits.universal_kernel.wave2.hybrid_retrieval import hybrid_search
from block_store.kits.universal_kernel.wave2.llm_provider import (
    get_provider as get_llm_provider,
)
from block_store.kits.universal_kernel.wave2.secure_ingestion import (
    IngestionRequest,
    validate,
)
from block_store.kits.universal_kernel.wave2.vector_store import Chunk, VectorStore
from block_store.kits.universal_kernel.wave3.json_audit_export import export_audit
from block_store.kits.universal_kernel.wave3.pdf_export import PDFBuilder
from block_store.kits.universal_kernel.wave3.xlsx_export import export_table


TENANT = "t-rag"
PROJECT = "p-rag"
DOCUMENT = (
    "The Universal Kernel is a neutral, fail-closed capability spine. "
    "It includes identity, authorization, scope isolation, rate limiting, "
    "audit evidence, and provenance verification. "
    "The intelligence wave adds secure ingestion, document parsing, "
    "embeddings, vector storage, hybrid retrieval, and grounded answers."
)
FILENAME = "kernel-overview.txt"


@pytest.fixture(autouse=True)
def _clean_audit_log():
    reset_audit_log()
    yield
    reset_audit_log()


def _embed_fn(text: str) -> list:
    provider = get_provider("hash")
    return provider.embed([text])["vectors"][0]


def test_rag_chain_end_to_end():
    # 1. Ingest a small plain-text document.
    content_bytes = DOCUMENT.encode("utf-8")
    request = IngestionRequest(
        filename=FILENAME,
        content_bytes=content_bytes,
        claimed_mime="text/plain",
        tenant_id=TENANT,
        project_id=PROJECT,
    )
    ingestion = validate(request)
    assert ingestion.ok is True
    assert ingestion.detected_mime == "text/plain"
    assert ingestion.honesty == "validated"

    record(
        event_type="rag_document_ingested",
        principal={"id": "rag-test-principal"},
        scope={"tenant_id": TENANT, "project_id": PROJECT},
        action="secure_ingestion.validate",
        outcome="success",
        payload={"filename": FILENAME, "digest": ingestion.digest},
    )

    # 2. Parse the document.
    document = parse(content_bytes, mime_type="text/plain", filename=FILENAME)
    assert document.honesty == "parsed"
    assert len(document.chunks) > 0

    # 3. Embed chunks with the deterministic embedding-provider fallback.
    embed_provider = get_provider("hash")
    embeddings = embed_provider.embed(document.chunks)
    assert embeddings["honesty"] == "deterministic_hash_fallback"
    assert embeddings["dimensions"] == EMBEDDING_DIMENSION
    assert len(embeddings["vectors"]) == len(document.chunks)
    for vector in embeddings["vectors"]:
        assert len(vector) == EMBEDDING_DIMENSION

    # 4. Upsert chunks into vector store scoped to tenant/project.
    store = VectorStore()
    chunks = [
        Chunk(
            id=f"chunk-{i}",
            text=text,
            vector=vector,
            metadata={
                "filename": FILENAME,
                "chunk_index": i,
                "source_class": "official_guidance",
            },
        )
        for i, (text, vector) in enumerate(zip(document.chunks, embeddings["vectors"]))
    ]
    upserted = store.upsert(TENANT, PROJECT, chunks)
    assert upserted == len(chunks)
    assert store.count(TENANT, PROJECT) == len(chunks)

    # 5. Run hybrid retrieval for a matching query.
    query = "What capabilities are in the Universal Kernel?"
    query_vector = _embed_fn(query)
    retrieval = hybrid_search(store, TENANT, PROJECT, query, query_vector, top_k=3)
    assert retrieval["honesty"] == "hybrid"
    assert len(retrieval["results"]) > 0
    top_result = retrieval["results"][0]
    assert "chunk_id" in top_result.source_citation
    assert "text_snippet" in top_result.source_citation

    # 6. Run grounded_answer for a question.
    llm = get_llm_provider("stub")
    answerer = GroundedAnswerer(retriever=store, llm_provider=llm, embed_fn=_embed_fn)
    answer = answerer.answer(TENANT, PROJECT, query, top_k=3)
    assert answer["honesty"] == "grounded"
    assert len(answer["citations"]) > 0
    assert any("chunk-" in c["chunk_id"] for c in answer["citations"])
    assert answer["answer"]

    record(
        event_type="rag_answer_grounded",
        principal={"id": "rag-test-principal"},
        scope={"tenant_id": TENANT, "project_id": PROJECT},
        action="grounded_answer.answer",
        outcome="success",
        payload={"question": query, "honesty": answer["honesty"]},
    )

    # 7. Run a second query for a topic not in the corpus.
    empty_answer = answerer.answer(
        "t-empty", "p-empty", "What is quantum chromodynamics?", top_k=3
    )
    assert empty_answer["honesty"] == "insufficient_sources"
    assert empty_answer["answer"] == "Insufficient sources."
    assert empty_answer["citations"] == []

    # 8. Export retrieved results to XLSX bytes.
    headers = ["chunk_id", "text_snippet", "score", "vector_score", "lexical_score"]
    rows = []
    for result in retrieval["results"]:
        citation = result.source_citation
        rows.append(
            [
                citation["chunk_id"],
                citation["text_snippet"],
                result.score,
                citation.get("vector_score"),
                citation.get("lexical_score"),
            ]
        )
    xlsx_bytes = export_table(headers=headers, rows=rows, title="rag_results")
    assert isinstance(xlsx_bytes, bytes)
    assert len(xlsx_bytes) > 0

    # 9. Export results to PDF bytes.
    pdf = PDFBuilder(title="RAG Results")
    pdf.add_heading("Retrieved Sources")
    for result in retrieval["results"]:
        pdf.add_paragraph(
            f"{result.source_citation['chunk_id']}: "
            f"{result.source_citation['text_snippet'][:200]}"
        )
    pdf_bytes = pdf.to_bytes()
    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert len(pdf_bytes) > 0

    # 10. Export audit records from the RAG run to JSON.
    audit_json = export_audit(_default_log.records(), include_payload=True, pretty=True)
    assert isinstance(audit_json, str)
    parsed = json.loads(audit_json)
    assert isinstance(parsed, list)
    assert len(parsed) >= 2
