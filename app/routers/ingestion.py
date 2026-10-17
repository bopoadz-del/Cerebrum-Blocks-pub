"""Ingestion pipeline router.

Exposes endpoints to upload files, paste raw text, or ingest a URL into the
pgvector-backed RAG store. All endpoints require a valid API key.
"""

import logging
import os
import uuid
from typing import Callable, Optional

import httpx
import shutil
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.core import vector_store
from app.core.chunking import chunk_text
from app.core.extraction import extract_text_from_file
from app.dependencies import require_api_key

logger = logging.getLogger(__name__)
router = APIRouter()

DATA_DIR = os.getenv("DATA_DIR", "./data")
os.makedirs(DATA_DIR, exist_ok=True)


class IngestTextRequest(BaseModel):
    tenant_id: str
    project_name: Optional[str] = None
    title: str
    text: str
    source_path: Optional[str] = None


class IngestUrlRequest(BaseModel):
    tenant_id: str
    project_name: Optional[str] = None
    url: str = Field(..., description="URL to download and ingest")


ExtractFn = Callable[[], dict]


async def _run_ingestion(
    tenant_id: str,
    project_name: Optional[str],
    title: str,
    source_path: str,
    extract_fn: ExtractFn,
) -> dict:
    """Create project/document/job, extract text, chunk, and store vectors."""
    project = await vector_store.ensure_project(
        tenant_id, name=project_name or "default"
    )
    if not project:
        raise HTTPException(status_code=503, detail="Vector store unavailable")

    document = await vector_store.create_document(
        project_id=project["id"],
        title=title,
        source_path=source_path,
        doc_metadata={"title": title, "source_path": source_path},
    )
    if not document:
        raise HTTPException(status_code=503, detail="Failed to create document")

    job = await vector_store.create_ingestion_job(document["id"])
    if not job:
        raise HTTPException(status_code=503, detail="Failed to create ingestion job")

    try:
        result = await extract_fn()
        if result.get("status") == "error":
            error = result.get("error", "Extraction failed")
            await vector_store.update_job_status(
                job["id"],
                status="failed",
                stage="extraction",
                error_message=error,
            )
            raise HTTPException(status_code=422, detail=error)

        text = result.get("text", "")
        pages = result.get("pages")
        chunks = chunk_text(text)
        records = [
            {
                "content": chunk,
                "metadata": {
                    "chunk_index": idx,
                    "source_path": source_path,
                    "pages": pages,
                },
            }
            for idx, chunk in enumerate(chunks)
        ]
        inserted = await vector_store.add_chunks(document["id"], records)
        await vector_store.update_job_status(
            job["id"],
            status="completed",
            stage="chunks_added",
            chunk_count=inserted,
        )
        return {
            "status": "success",
            "job_id": str(job["id"]),
            "document_id": str(document["id"]),
            "project_id": str(project["id"]),
            "chunks": inserted,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Ingestion failed for document %s", document["id"])
        await vector_store.update_job_status(
            job["id"],
            status="failed",
            stage="unknown",
            error_message=str(exc),
        )
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}")


def _safe_filename(name: str) -> str:
    """Sanitize a filename and prevent path traversal."""
    name = name.strip()
    if not name or name in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return os.path.basename(name.replace("\\", "/"))


@router.post("/ingestion/upload")
async def ingestion_upload(
    file: UploadFile = File(...),
    tenant_id: str = Form(...),
    project_name: Optional[str] = Form(None),
    auth: dict = Depends(require_api_key),
):
    """Upload a file and ingest it into the vector store."""
    original_name = _safe_filename(file.filename or "unknown")
    file_id = str(uuid.uuid4())[:8]
    filename = f"{file_id}_{original_name}"
    filepath = os.path.join(DATA_DIR, filename)

    try:
        with open(filepath, "wb") as out:
            shutil.copyfileobj(file.file, out)
    except Exception as exc:
        logger.exception("Failed to save uploaded file")
        raise HTTPException(status_code=500, detail=f"File save failed: {exc}")

    return await _run_ingestion(
        tenant_id=tenant_id,
        project_name=project_name,
        title=original_name,
        source_path=filepath,
        extract_fn=lambda: extract_text_from_file(filepath),
    )


@router.post("/ingestion/text")
async def ingestion_text(
    request: IngestTextRequest, auth: dict = Depends(require_api_key)
):
    """Ingest raw text into the vector store."""
    # SECURITY: never write to a caller-supplied path. ``request.source_path``
    # is untrusted and reaching ``open(..., "w")`` with it is an arbitrary file
    # write (overwrite app code -> RCE) for any API-key holder. Always persist
    # to a generated path inside DATA_DIR; the caller's source_path, if any, is
    # kept only as a provenance *label* in metadata and never touches the fs.
    write_path = os.path.join(DATA_DIR, f"{str(uuid.uuid4())[:8]}_text.txt")
    source_label = request.source_path or write_path
    try:
        with open(write_path, "w", encoding="utf-8") as out:
            out.write(request.text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save text: {exc}")

    async def _extract_text() -> dict:
        return {
            "status": "success",
            "text": request.text,
            "pages": None,
            "source_path": source_label,
        }

    return await _run_ingestion(
        tenant_id=request.tenant_id,
        project_name=request.project_name,
        title=request.title,
        source_path=source_label,
        extract_fn=_extract_text,
    )


@router.post("/ingestion/url")
async def ingestion_url(
    request: IngestUrlRequest, auth: dict = Depends(require_api_key)
):
    """Download a URL and ingest it into the vector store."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            response = await client.get(request.url)
            response.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Download failed: {exc}")

    original_name = os.path.basename(request.url.split("?")[0]) or "download"
    if "." not in original_name:
        content_type = response.headers.get("content-type", "").split(";")[0].strip()
        ext_map = {
            "application/pdf": ".pdf",
            "text/plain": ".txt",
            "text/markdown": ".md",
            "text/csv": ".csv",
            "application/json": ".json",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        }
        original_name += ext_map.get(content_type, ".bin")

    original_name = _safe_filename(original_name)
    file_id = str(uuid.uuid4())[:8]
    filename = f"{file_id}_{original_name}"
    filepath = os.path.join(DATA_DIR, filename)

    try:
        with open(filepath, "wb") as out:
            out.write(response.content)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save downloaded file: {exc}")

    return await _run_ingestion(
        tenant_id=request.tenant_id,
        project_name=request.project_name,
        title=original_name,
        source_path=filepath,
        extract_fn=lambda: extract_text_from_file(filepath),
    )


@router.get("/ingestion/jobs/{job_id}")
async def get_job(job_id: str, auth: dict = Depends(require_api_key)):
    """Return the status of a single ingestion job."""
    job = await vector_store.get_ingestion_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
