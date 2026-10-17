"""Capture Router — POST /capture/upload endpoint.

Accepts multipart image uploads from any client:
  - Ksnip (desktop)
  - Termux (Android)
  - Web form
  - curl / any HTTP client
"""

import os
import re
import shutil
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.dependencies import require_api_key, get_block_instance
from app.core.http_errors import classify_block_error as _classify_block_error

router = APIRouter()

# capture_id is interpolated into the saved-file path via f"{fid}_{name}".
# Without sanitisation, an attacker could pass capture_id="../../tmp/x"
# and write outside CAPTURE_DATA_DIR. Restrict to a tight identifier set;
# the block uses the value internally too, so don't be more lenient here
# than the downstream consumer is.
_CAPTURE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")

CAPTURE_DATA_DIR = os.path.join(os.getenv("DATA_DIR", "./data"), "captures")
os.makedirs(CAPTURE_DATA_DIR, exist_ok=True)

MAX_CAPTURE_SIZE = int(os.getenv("MAX_CAPTURE_SIZE", "10485760"))  # 10MB
ALLOWED_IMAGE_TYPES = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"
}


class CaptureResponse(BaseModel):
    capture_id: str
    status: str
    source: str
    raw_text: str
    clean_text: str
    summary: str
    entities: list
    tags: list
    language_detected: str
    ocr_confidence: float
    ocr_engine: str
    timestamp: str
    memory_id: Optional[str] = None


@router.post("/capture/upload", response_model=CaptureResponse)
async def capture_upload(
    file: UploadFile = File(...),
    source: str = Form(default="web"),
    user_id: str = Form(default="anonymous"),
    capture_id: Optional[str] = Form(default=None),
    auth: dict = Depends(require_api_key),
):
    """Upload an image → OCR → AI structure → vector store.

    **Clients:**
    - Ksnip: `curl -F file=@screenshot.png -F source=ksnip ...`
    - Termux: `curl -F file=@screencap.png -F source=termux ...`
    - Web: standard HTML form
    """
    # Validate
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    original_name = os.path.basename(file.filename.replace("\\", "/"))
    _, ext = os.path.splitext(original_name.lower())
    if ext not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail=f"Image type '{ext}' not allowed")

    # Save to disk
    if capture_id is not None and not _CAPTURE_ID_RE.match(capture_id):
        raise HTTPException(
            status_code=400,
            detail="capture_id must match [a-zA-Z0-9_-]{1,32}",
        )
    fid = capture_id or str(uuid.uuid4())[:8]
    stored_name = f"{fid}_{original_name}"
    # Defence in depth: even after sanitising fid + stripping basename
    # from the upload, double-check the resolved path stays in
    # CAPTURE_DATA_DIR.
    capture_root = os.path.realpath(CAPTURE_DATA_DIR)
    file_path = os.path.realpath(os.path.join(CAPTURE_DATA_DIR, stored_name))
    if not (file_path == capture_root or file_path.startswith(capture_root + os.sep)):
        raise HTTPException(status_code=400, detail="Invalid file path")

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save capture: {e}")
    finally:
        file.file.close()

    # Get block and process
    try:
        block = get_block_instance("capture")
        result = await block.process(
            {"file_path": file_path},
            {
                "action": "capture",
                "source": source,
                "user_id": user_id,
                "capture_id": fid,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Capture processing failed: {e}")

    if result.get("status") == "error":
        err = result.get("error", "Processing error")
        raise HTTPException(status_code=_classify_block_error(result), detail=err)

    # Flatten to response model
    inner = result.get("result", result)
    return CaptureResponse(
        capture_id=inner.get("capture_id", fid),
        status="success",
        source=inner.get("source", source),
        raw_text=inner.get("raw_text", ""),
        clean_text=inner.get("clean_text", ""),
        summary=inner.get("summary", ""),
        entities=inner.get("entities", []),
        tags=inner.get("tags", []),
        language_detected=inner.get("language_detected", "unknown"),
        ocr_confidence=inner.get("ocr_confidence", 0.0),
        ocr_engine=inner.get("ocr_engine", "unknown"),
        timestamp=inner.get("timestamp", ""),
        memory_id=inner.get("memory_id"),
    )


@router.post("/capture/ocr")
async def capture_ocr_only(
    file: UploadFile = File(...),
    languages: str = Form(default="ara+eng"),
    auth: dict = Depends(require_api_key),
):
    """OCR-only endpoint: image → raw text."""
    original_name = os.path.basename(file.filename.replace("\\", "/"))
    fid = str(uuid.uuid4())[:8]
    file_path = os.path.join(CAPTURE_DATA_DIR, f"{fid}_{original_name}")

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    file.file.close()

    block = get_block_instance("capture")
    result = await block.process(
        {"file_path": file_path},
        {"action": "ocr", "languages": languages},
    )

    if result.get("status") == "error":
        err = result.get("error", "OCR failed")
        raise HTTPException(status_code=_classify_block_error(result), detail=err)

    inner = result.get("result", result)
    return {
        "capture_id": fid,
        "raw_text": inner.get("text", ""),
        "confidence": inner.get("confidence", 0),
        "engine": inner.get("engine", "unknown"),
        "word_count": inner.get("word_count", 0),
    }


@router.post("/capture/structure")
async def capture_structure_text(
    text: str = Form(...),
    llm_provider: Optional[str] = Form(default=None),
    auth: dict = Depends(require_api_key),
):
    """Structure raw text via LLM (no image needed)."""
    block = get_block_instance("capture")
    params = {"action": "structure"}
    if llm_provider:
        params["llm_provider"] = llm_provider

    # Wrap the block call: when the underlying LLM provider raises (which the
    # block's _llm_chat does via httpx.HTTPStatusError instead of returning a
    # status:error envelope), we'd otherwise leak a bare "Internal Server
    # Error" text response. Surface the actual failure with a sensible code.
    try:
        result = await block.process(text, params)
    except Exception as e:
        err = str(e) or e.__class__.__name__
        raise HTTPException(status_code=_classify_block_error(e), detail=err)

    if result.get("status") == "error":
        err = result.get("error", "Structuring failed")
        raise HTTPException(status_code=_classify_block_error(result), detail=err)

    inner = result.get("result", result)
    return {
        "clean_text": inner.get("clean_text", text),
        "summary": inner.get("summary", ""),
        "entities": inner.get("entities", []),
        "tags": inner.get("tags", []),
        "language": inner.get("language", "unknown"),
    }


@router.post("/capture/search")
async def capture_search(
    query: str = Form(...),
    n_results: int = Form(default=5),
    auth: dict = Depends(require_api_key),
):
    """Semantic search across stored captures."""
    block = get_block_instance("capture")
    result = await block.process(query, {"action": "search", "n_results": n_results})

    if result.get("status") == "error":
        err = result.get("error", "Search failed")
        raise HTTPException(status_code=_classify_block_error(result), detail=err)

    return result.get("result", result)
