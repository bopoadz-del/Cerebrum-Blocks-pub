"""Marker PDF Block - PDF text-layer extraction to Markdown-compatible text.

The block reads the PDF's embedded text layer with ``pypdfium2`` and falls
back to PyMuPDF (``fitz``) when pypdfium2 is absent or cannot open the file.
Neither engine depends on Pillow.

It used to wrap ``marker-pdf``. Every marker-pdf release up to 2.0.0, and
the surya-ocr it requires (0.22.1), pins ``pillow<11``, so every product
that vendored this block shipped Pillow 10.4.0 and its published advisories.

What the block does NOT do: OCR. A page with no text layer (a scanned
image) yields no text. That is never silent: such pages are listed in
``pages_without_text``, a document where no page has text is an error, and
the error says OCR is not provided here.
"""

import logging
import os
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.typed_block import TypedBlock, Schema, ContentType

logger = logging.getLogger(__name__)


class _EngineMissing(Exception):
    """The engine's package is not installed."""


def _pages_pypdfium2(pdf_path: str) -> List[str]:
    try:
        import pypdfium2 as pdfium
    except ImportError as e:
        raise _EngineMissing(str(e)) from e
    doc = pdfium.PdfDocument(pdf_path)
    try:
        texts = []
        for index in range(len(doc)):
            page = doc[index]
            textpage = page.get_textpage()
            try:
                texts.append(textpage.get_text_range())
            finally:
                textpage.close()
                page.close()
        return texts
    finally:
        doc.close()


def _pages_pymupdf(pdf_path: str) -> List[str]:
    try:
        import fitz
    except ImportError as e:
        raise _EngineMissing(str(e)) from e
    with fitz.open(pdf_path) as doc:
        return [page.get_text() for page in doc]


#: Tried in order; the first engine that opens the file is the answer.
ENGINES: Tuple[Tuple[str, Callable[[str], List[str]]], ...] = (
    ("pypdfium2", _pages_pypdfium2),
    ("pymupdf", _pages_pymupdf),
)


def _normalise(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _try_marker(pdf_path: str) -> Optional[Dict[str, Any]]:
    """Extract the text layer of ``pdf_path``.

    Returns ``{"text", "pages", "engine", "pages_without_text"}`` from the
    first engine that opens the file, or ``None`` when no engine is installed
    or none can read it -- callers such as the ``pdf`` block fall through to
    their own parsers on ``None``. ``extract`` reports which of those it was.
    """
    result, _ = extract(pdf_path)
    return result


def extract(pdf_path: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """``(result, "")`` on success, ``(None, reason)`` otherwise."""
    missing, failed = [], []
    for name, read_pages in ENGINES:
        try:
            pages = [_normalise(t) for t in read_pages(pdf_path)]
        except _EngineMissing:
            missing.append(name)
            continue
        except Exception as e:  # a parser's own error type is engine-specific
            logger.warning("%s could not read %s: %s", name, pdf_path, e)
            failed.append(f"{name}: {e}")
            continue
        return (
            {
                "text": "\n\n".join(t for t in pages if t),
                "pages": len(pages),
                "engine": name,
                "pages_without_text": [i + 1 for i, t in enumerate(pages) if not t],
            },
            "",
        )
    if failed:
        return None, "PDF could not be read (" + "; ".join(failed) + ")"
    return None, (
        "no PDF engine installed (tried " + ", ".join(missing) + "). "
        "Install it with: pip install pypdfium2"
    )


#: Said wherever a page had no text layer, so the gap is never silent.
NO_OCR = (
    "this block reads the PDF text layer only and does not OCR scanned "
    "pages; route image-only pages to an OCR block"
)


class MarkerBlock(TypedBlock):
    """Extract Markdown-compatible text from the text layer of PDF files."""

    name = "marker"
    version = "1.0.0"
    description = (
        "PDF to Markdown-compatible text from the PDF text layer "
        "(pypdfium2, PyMuPDF fallback); no OCR"
    )
    layer = 3
    tags = ["domain", "documents", "pdf", "markdown", "typed"]
    requires = []

    default_config = {"max_chars": 200000}

    input_schema = Schema(
        content_type=ContentType.FILE,
        required_fields=["file_path"],
        optional_fields=["path", "url"],
        format_hints={"accept": [".pdf"]},
    )

    output_schema = Schema(
        content_type=ContentType.TEXT,
        required_fields=["text"],
        optional_fields=["pages", "filename", "status", "engine", "pages_without_text", "warnings"],
        format_hints={"max_chars": 200000},
    )

    ui_schema = {
        "input": {
            "type": "file",
            "accept": [".pdf"],
            "placeholder": "Upload PDF...",
            "multiline": False,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "text", "type": "text", "label": "Markdown"},
                {"name": "pages", "type": "number", "label": "Pages"},
            ],
        },
        "quick_actions": [
            {
                "icon": "📄",
                "label": "Extract Markdown",
                "prompt": "Convert this PDF to clean Markdown",
            },
            {
                "icon": "📊",
                "label": "Extract Tables",
                "prompt": "Extract all tables from this PDF as Markdown tables",
            },
        ],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Extract the text layer of a PDF."""
        params = params or {}
        max_chars = params.get("max_chars", 200000)

        # Resolve URL input
        url = None
        if isinstance(input_data, dict):
            url = input_data.get("url")
            if not url:
                raw = input_data.get("text") or input_data.get("input") or ""
                if raw.startswith("http"):
                    url = raw
        elif isinstance(input_data, str) and input_data.startswith("http"):
            url = input_data

        if url:
            import httpx

            try:
                from app.core.url_guard import validate_public_url
                url = validate_public_url(url)  # SSRF guard
                async with httpx.AsyncClient(follow_redirects=False) as client:
                    response = await client.get(url, timeout=30)
                    response.raise_for_status()
                    suffix = ".pdf" if ".pdf" in url.lower() else ".tmp"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                        f.write(response.content)
                        input_data = f.name
            except Exception as e:
                return {
                    "status": "error",
                    "text": "",
                    "pages": 0,
                    "error": f"Download failed: {str(e)}",
                }

        pdf_path = self._get_pdf_path(input_data)
        if not pdf_path:
            return {"status": "error", "text": "", "pages": 0, "error": "No PDF provided"}
        if not os.path.exists(pdf_path):
            return {
                "status": "error",
                "text": "",
                "pages": 0,
                "error": f"File not found: {pdf_path}",
            }

        result, reason = extract(pdf_path)
        if result is None:
            return {"status": "error", "text": "", "pages": 0, "error": reason}

        blank = result["pages_without_text"]
        if result["pages"] and len(blank) == result["pages"]:
            return {
                "status": "error",
                "text": "",
                "pages": result["pages"],
                "pages_without_text": blank,
                "engine": result["engine"],
                "error": f"no page has a text layer: {NO_OCR}",
            }

        out = {
            "status": "success",
            "text": result["text"][:max_chars],
            "pages": result["pages"],
            "filename": os.path.basename(pdf_path),
            "file_path": pdf_path,
            "engine": result["engine"],
            "pages_without_text": blank,
        }
        if blank:
            out["warnings"] = [f"pages {blank} have no text layer: {NO_OCR}"]
        return out

    def _get_pdf_path(self, input_data: Any) -> str:
        """Extract PDF path from input, writing bytes to a temp file if needed."""
        if isinstance(input_data, bytes):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
                f.write(input_data)
                return f.name
        if isinstance(input_data, str):
            return input_data
        if isinstance(input_data, dict):
            file_bytes = input_data.get("file") or input_data.get("pdf_bytes") or input_data.get("bytes")
            if isinstance(file_bytes, bytes):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
                    f.write(file_bytes)
                    return f.name
            return input_data.get("file_path") or input_data.get("path") or input_data.get("url")
        return None
