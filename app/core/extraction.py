"""Text extraction from common document formats."""

import logging
import os

logger = logging.getLogger(__name__)


async def extract_text_from_file(file_path: str) -> dict:
    """Extract text from ``file_path``.

    Returns:
        ``{"status": "success", "text": str, "pages": int|None, "source_path": str}``
        or ``{"status": "error", "error": str}``.
    """
    if not file_path or not os.path.exists(file_path):
        return {"status": "error", "error": f"File not found: {file_path}"}

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        from app.blocks.pdf import PDFBlock

        block = PDFBlock()
        result = await block.process(file_path)
        if result.get("status") == "error":
            return {
                "status": "error",
                "error": result.get("error", "PDF extraction failed"),
            }
        return {
            "status": "success",
            "text": result.get("text", ""),
            "pages": result.get("pages"),
            "source_path": file_path,
        }

    if ext in (".txt", ".md", ".csv", ".json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
            return {
                "status": "success",
                "text": text,
                "pages": None,
                "source_path": file_path,
            }
        except Exception as exc:
            return {"status": "error", "error": f"Read failed: {exc}"}

    if ext == ".docx":
        try:
            import docx
        except ImportError:
            return {
                "status": "error",
                "error": "python-docx not installed; install python-docx to read .docx files",
            }
        try:
            document = docx.Document(file_path)
            text = "\n".join(p.text for p in document.paragraphs if p.text)
            return {
                "status": "success",
                "text": text,
                "pages": None,
                "source_path": file_path,
            }
        except Exception as exc:
            return {"status": "error", "error": f"DOCX read failed: {exc}"}

    return {"status": "error", "error": f"Unsupported file type: {ext}"}
