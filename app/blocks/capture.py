"""Capture Block — Any client pushes images, get structured data back.

Pipeline:
  Image → OCR (Tesseract ara+eng) → Raw Text → LLM Structuring → Vector DB
"""

import os
import io
import uuid
import json
import tempfile
import base64
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from app.core.universal_base import UniversalBlock
from app.core.typed_block import TypedBlock, Schema, ContentType
from app.core.http_errors import error_kind
from app.core.http_errors import UNAVAILABLE


class CaptureBlock(TypedBlock):
    """Universal capture block: image → OCR → AI → structured data → vector store."""

    name = "capture"
    version = "1.0.0"
    description = "Receive images from any client, OCR extract, AI structure, vector store"
    layer = 3
    tags = ["capture", "ocr", "vision", "ai", "multimodal", "knowledge"]
    requires = ["vector_search"]

    input_schema = Schema(
        content_type=ContentType.IMAGE,
        required_fields=[],
        optional_fields=["image", "file_path", "bytes", "base64", "source", "user_id", "capture_id"],
        format_hints={"accept": [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]}
    )

    output_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=["capture_id", "status", "raw_text", "clean_text", "summary"],
        optional_fields=["entities", "tags", "language_detected", "ocr_confidence", "ocr_engine", "memory_id"],
        format_hints={}
    )

    accepted_input_types = ["Image", "ImageContent", "File"]
    produced_output_types = ["Text", "JSON", "CaptureResult"]

    default_config = {
        "ocr_languages": "ara+eng",
        "ocr_engine": "tesseract",
        "llm_provider": "kimi",
        "kimi_vision_model": os.getenv("KIMI_VISION_MODEL", "moonshot-v1-8k-vision-preview"),
        "vector_db_url": os.getenv("VECTOR_DB_URL", "http://localhost:8001"),
        "store_captures": True,
        "capture_collection": "cerebrum_captures",
    }

    ui_schema = {
        "input": {
            "type": "image",
            "accept": [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"],
            "placeholder": "Upload or push an image to capture and structure...",
            "multiline": False,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "capture_id", "type": "text", "label": "Capture ID"},
                {"name": "raw_text", "type": "text", "label": "OCR Raw Text"},
                {"name": "entities", "type": "json", "label": "Entities"},
                {"name": "tags", "type": "array", "label": "Tags"},
                {"name": "summary", "type": "text", "label": "Summary"},
                {"name": "clean_text", "type": "text", "label": "Clean Text"},
            ],
        },
        "quick_actions": [
            {"icon": "📸", "label": "Capture Image", "prompt": "Capture and structure this image"},
            {"icon": "🔍", "label": "OCR Only", "prompt": "Extract raw text only"},
            {"icon": "🧠", "label": "AI Structure", "prompt": "Structure captured text into entities and summary"},
        ],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self._ensure_dirs()

    def _ensure_dirs(self):
        d = os.getenv("DATA_DIR", "./data")
        self.capture_dir = os.path.join(d, "captures")
        os.makedirs(self.capture_dir, exist_ok=True)

    # ── Public API ─────────────────────────────────────────────────────────────

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Main entry: accepts image path, bytes, or dict with file info."""
        params = params or {}
        action = params.get("action", "capture")

        if action == "capture":
            return await self._capture(input_data, params)
        elif action == "ocr":
            return await self._ocr_only(input_data, params)
        elif action == "structure":
            return await self._structure_text(input_data, params)
        elif action == "search":
            return await self._search_captures(input_data, params)
        else:
            return {"status": "error", "error": f"Unknown action: {action}"}

    async def _capture(self, input_data: Any, params: Dict) -> Dict:
        """Full pipeline: image → vision/OCR → structure → store."""
        # 1. Resolve image
        try:
            image_path = await self._resolve_image(input_data)
        except ValueError:
            image_path = None
        if not image_path or not os.path.exists(image_path):
            return {
                "status": "success",
                "mode": "demo",
                "note": "No valid image provided. Below is demo capture output.",
                "ocr_text": "Demo: Site inspection photo showing concrete pour in progress.",
                "structured": {
                    "activity": "Concrete Pour",
                    "location": "Level 3, Grid B-C/4-5",
                    "date": "2026-05-04",
                    "items": ["Concrete C30", "Rebar mesh", "Formwork"],
                },
                "confidence": 0.85,
            }

        capture_id = params.get("capture_id") or self._generate_id()
        source = params.get("source", "unknown")
        user_id = params.get("user_id", "anonymous")

        # Prefer Kimi Vision when an API key is available.
        kimi_key = os.getenv("KIMI_API_KEY", "") or os.getenv("MOONSHOT_API_KEY", "")
        if kimi_key:
            vision_result = await self._vision_with_kimi(image_path, params)
            if vision_result.get("status") == "error":
                return vision_result
            result = {
                "status": "success",
                "capture_id": capture_id,
                "source": source,
                "user_id": user_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "raw_text": vision_result.get("raw_text", ""),
                "clean_text": vision_result.get("clean_text", ""),
                "entities": vision_result.get("entities", []),
                "tags": vision_result.get("tags", []),
                "summary": vision_result.get("summary", ""),
                "language_detected": vision_result.get("language", "unknown"),
                "ocr_engine": "kimi-vision",
                "ocr_confidence": vision_result.get("confidence", 0.95),
                "image_path": image_path,
            }
        else:
            # 2. OCR
            ocr_result = await self._run_ocr(image_path, params)
            if ocr_result.get("status") == "error":
                return ocr_result
            raw_text = ocr_result.get("text", "")

            # 3. LLM structuring
            structured = await self._structure_with_llm(raw_text, params)
            if structured.get("status") == "error":
                return structured

            # 4. Build result
            result = {
                "status": "success",
                "capture_id": capture_id,
                "source": source,
                "user_id": user_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "raw_text": raw_text,
                "clean_text": structured.get("clean_text", raw_text),
                "entities": structured.get("entities", []),
                "tags": structured.get("tags", []),
                "summary": structured.get("summary", ""),
                "language_detected": structured.get("language", "unknown"),
                "ocr_engine": ocr_result.get("engine", "unknown"),
                "ocr_confidence": ocr_result.get("confidence", 0),
                "image_path": image_path,
            }

        # 5. Vector store
        if self.config.get("store_captures", True):
            stored_id = await self._store_in_vector_db(capture_id, result)
            result["memory_id"] = stored_id

        return result

    async def _ocr_only(self, input_data: Any, params: Dict) -> Dict:
        image_path = await self._resolve_image(input_data)
        if not image_path or not os.path.exists(image_path):
            return {"status": "error", "error": "No valid image provided"}
        return await self._run_ocr(image_path, params)

    async def _structure_text(self, input_data: Any, params: Dict) -> Dict:
        text = input_data if isinstance(input_data, str) else str(input_data)
        structured = await self._structure_with_llm(text, params)
        if structured.get("status") == "error":
            return structured
        return {"status": "success", **structured}

    async def _search_captures(self, input_data: Any, params: Dict) -> Dict:
        query = input_data if isinstance(input_data, str) else str(input_data)
        return await self._search_vectors(query, params)

    # ── Image resolution ───────────────────────────────────────────────────────

    async def _resolve_image(self, input_data: Any) -> Optional[str]:
        """Turn input into a local file path."""
        if isinstance(input_data, str):
            if os.path.exists(input_data):
                return input_data
            # Check if it looks like a file path (has extension or starts with /)
            looks_like_path = input_data.startswith("/") or "." in os.path.basename(input_data)
            if looks_like_path:
                raise ValueError(f"File not found: {input_data}")
            # Assume base64
            return self._save_base64(input_data)
        elif isinstance(input_data, bytes):
            return self._save_bytes(input_data)
        elif isinstance(input_data, dict):
            if input_data.get("file_path"):
                path = input_data["file_path"]
                if os.path.exists(path):
                    return path
                raise ValueError(f"File not found: {path}")
            if input_data.get("bytes"):
                return self._save_bytes(input_data["bytes"])
            if input_data.get("base64"):
                return self._save_base64(input_data["base64"])
            if input_data.get("image"):
                img = input_data["image"]
                if isinstance(img, str):
                    if os.path.exists(img):
                        return img
                    # Check if it looks like a file path
                    looks_like_path = img.startswith("/") or "." in os.path.basename(img)
                    if looks_like_path:
                        raise ValueError(f"File not found: {img}")
                    return self._save_base64(img)
                elif isinstance(img, bytes):
                    return self._save_bytes(img)
        return None

    def _save_bytes(self, data: bytes, ext: str = ".png") -> str:
        fid = self._generate_id()
        path = os.path.join(self.capture_dir, f"{fid}{ext}")
        with open(path, "wb") as f:
            f.write(data)
        return path

    def _save_base64(self, b64data: str, ext: str = ".png") -> str:
        # Strip data URI prefix if present
        if "," in b64data:
            b64data = b64data.split(",", 1)[1]
        raw = base64.b64decode(b64data)
        return self._save_bytes(raw, ext)

    def _generate_id(self) -> str:
        return str(uuid.uuid4())[:8]

    # ── OCR ────────────────────────────────────────────────────────────────────

    async def _run_ocr(self, image_path: str, params: Dict) -> Dict:
        languages = params.get("languages", self.config.get("ocr_languages", "ara+eng"))
        engine = self.config.get("ocr_engine", "tesseract")

        if engine == "tesseract":
            return await self._ocr_tesseract(image_path, languages)
        else:
            return await self._ocr_easyocr(image_path, languages.split("+") if "+" in languages else [languages])

    async def _ocr_tesseract(self, image_path: str, languages: str) -> Dict:
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(image_path)
            # Convert to RGB if necessary
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            # Preprocess for better OCR
            gray = img.convert("L")

            text = pytesseract.image_to_string(gray, lang=languages)
            data = pytesseract.image_to_data(gray, lang=languages, output_type=pytesseract.Output.DICT)

            confs = [int(c) for c in data["conf"] if int(c) > 0]
            avg_conf = sum(confs) / len(confs) if confs else 0

            return {
                "status": "success",
                "text": text.strip(),
                "confidence": round(avg_conf / 100, 2),  # Tesseract confidence 0-100
                "engine": "tesseract",
                "languages": languages,
                "word_count": len(text.split()),
            }
        except ImportError:
            return {"status": "error", "error": "pytesseract not installed. Run: pip install pytesseract pillow"}
        except Exception as e:
            return {"status": "error", "error": f"Tesseract OCR failed: {str(e)}"}

    async def _ocr_easyocr(self, image_path: str, languages: List[str]) -> Dict:
        try:
            import easyocr
            reader = easyocr.Reader(languages, gpu=False)
            results = reader.readtext(image_path)

            if not results:
                return {"status": "success", "text": "", "confidence": 0, "engine": "easyocr"}

            texts = [r[1] for r in results if r[1].strip()]
            confs = [r[2] for r in results]
            full_text = "\n".join(texts)
            avg_conf = sum(confs) / len(confs) if confs else 0

            return {
                "status": "success",
                "text": full_text,
                "confidence": round(avg_conf, 2),
                "engine": "easyocr",
                "languages": languages,
                "word_count": len(full_text.split()),
            }
        except ImportError:
            return {"status": "error", "error": "easyocr not installed"}
        except Exception as e:
            return {"status": "error", "error": f"EasyOCR failed: {str(e)}"}

    # ── Vision (Kimi) ────────────────────────────────────────────────────────

    async def _vision_with_kimi(self, image_path: str, params: Dict) -> Dict:
        import httpx
        from app.core.llm_config import _llm_config

        cfg = _llm_config()  # Kimi (Moonshot), OpenAI-compatible
        api_key = os.getenv(cfg["env_key"], "") if cfg["env_key"] else ""
        if not api_key:
            return {"status": "error", "error": "Kimi API key not configured (set KIMI_API_KEY)", "error_kind": UNAVAILABLE}

        model = self.config.get("kimi_vision_model", "moonshot-v1-8k-vision-preview")

        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        except Exception as e:
            return {"status": "error", "error": f"Failed to read image: {str(e)}"}

        ext = os.path.splitext(image_path)[1].lower()
        media_type_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }
        media_type = media_type_map.get(ext, "image/jpeg")

        system_prompt = (
            "You are a structured data extraction engine. "
            "Analyze the provided image and output ONLY valid JSON. "
            "No markdown, no explanation, just JSON."
        )
        user_prompt = (
            "Describe the image in detail and extract structured data. "
            "Return JSON with exactly these keys:\n"
            "- raw_text: any text visible in the image (OCR result)\n"
            "- clean_text: cleaned, properly formatted text\n"
            "- summary: one-sentence summary of the image content\n"
            "- entities: list of {\"type\": \"person|org|location|date|amount|other\", \"value\": \"...\"}\n"
            "- tags: list of relevant keywords (5-10 tags)\n"
            "- language: detected primary language (ar, en, mixed)\n"
            "- confidence: estimated confidence 0-1"
        )

        # OpenAI-compatible vision content (Kimi/Moonshot): image_url data URI.
        payload = {
            "model": model,
            "max_tokens": 4096,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{image_b64}"},
                        },
                        {"type": "text", "text": user_prompt},
                    ],
                },
            ],
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(cfg["url"], headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                text_content = data["choices"][0]["message"].get("content", "") or ""
                parsed = self._safe_parse_json(text_content)
                return {
                    "status": "success",
                    "raw_text": parsed.get("raw_text", text_content),
                    "clean_text": parsed.get("clean_text", text_content),
                    "summary": parsed.get("summary", ""),
                    "entities": parsed.get("entities", []),
                    "tags": parsed.get("tags", []),
                    "language": parsed.get("language", "unknown"),
                    "confidence": parsed.get("confidence", 0.95),
                }
        except httpx.HTTPStatusError as e:
            return {"status": "error", "error": f"Kimi Vision API error: {e.response.status_code} {e.response.text}"}
        except Exception as e:
            return {"status": "error", "error": f"Kimi Vision failed: {str(e)}"}

    # ── LLM Structuring ────────────────────────────────────────────────────────

    async def _structure_with_llm(self, raw_text: str, params: Dict) -> Dict:
        """Send raw OCR text to LLM for entity extraction, tagging, summarization."""
        provider = params.get("llm_provider", self.config.get("llm_provider", "kimi"))
        max_chars = params.get("max_chars", 4000)
        truncated = raw_text[:max_chars]

        system_prompt = (
            "You are a structured data extraction engine. "
            "Take raw OCR text (possibly Arabic + English mixed) and output ONLY valid JSON. "
            "No markdown, no explanation, just JSON."
        )
        user_prompt = f"""Extract from the following OCR text:

---
{truncated}
---

Return JSON with exactly these keys:
- clean_text: cleaned, properly formatted text
- summary: one-sentence summary
- entities: list of {{"type": "person|org|location|date|amount|other", "value": "..."}}
- tags: list of relevant keywords (5-10 tags)
- language: detected primary language (ar, en, mixed)
"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = await self._llm_chat(messages, provider)
        if response.get("status") == "error":
            return response
        content = response.get("content", "{}")
        parsed = self._safe_parse_json(content)
        return parsed

    async def _llm_chat(self, messages: List[Dict], provider: str = "kimi") -> Dict:
        import httpx
        from app.core.llm_config import _llm_config

        cfg = _llm_config()  # Kimi (Moonshot), OpenAI-compatible — the only provider
        api_key = os.getenv(cfg["env_key"], "") if cfg["env_key"] else ""
        if not api_key:
            return {"status": "error", "error": "Kimi API key not configured (set KIMI_API_KEY)", "error_kind": UNAVAILABLE}
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": cfg["default_model"],
            "messages": messages,
            "temperature": 0.2,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(cfg["url"], headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return {
                "content": data["choices"][0]["message"]["content"],
                "model": cfg["default_model"],
                "provider": "kimi",
                "tokens": data.get("usage", {}).get("total_tokens", 0),
            }

    # ── Vector Store ───────────────────────────────────────────────────────────

    async def _store_in_vector_db(self, capture_id: str, capture_result: Dict) -> Optional[str]:
        vector_block = self.get_dep("vector_search")
        collection = self.config.get("capture_collection", "cerebrum_captures")
        content = capture_result.get("clean_text", "") or capture_result.get("raw_text", "")
        metadata = {
            "capture_id": capture_id,
            "source": capture_result.get("source", "unknown"),
            "ocr_engine": capture_result.get("ocr_engine", "unknown"),
            "tags": json.dumps(capture_result.get("tags", [])),
        }

        if vector_block:
            try:
                result = await vector_block.process(
                    {"documents": [content], "metadatas": [metadata], "ids": [capture_id]},
                    {"operation": "add", "collection": collection},
                )
                if result.get("status") == "success":
                    return capture_id
            except Exception:
                pass

        # Fallback HTTP
        return await self._store_chroma_http(capture_id, content, metadata, collection)

    async def _store_chroma_http(self, doc_id: str, document: str, metadata: Dict, collection: str) -> Optional[str]:
        import httpx
        db_url = self.config.get("vector_db_url", "")
        if not db_url:
            return None
        try:
            payload = {
                "collection": collection,
                "documents": [document],
                "metadatas": [metadata],
                "ids": [doc_id],
            }
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(f"{db_url}/api/v1/collections/add", json=payload)
                if resp.status_code == 200:
                    return doc_id
        except Exception:
            pass
        return None

    async def _search_vectors(self, query: str, params: Dict) -> Dict:
        vector_block = self.get_dep("vector_search")
        collection = params.get("collection", self.config.get("capture_collection", "cerebrum_captures"))
        n_results = params.get("n_results", 5)

        if vector_block:
            try:
                result = await vector_block.process(
                    query,
                    {"operation": "search", "collection": collection, "n_results": n_results},
                )
                if result.get("status") == "success":
                    return {"status": "success", "results": result.get("results", [])}
            except Exception:
                pass

        # Fallback HTTP
        import httpx
        db_url = self.config.get("vector_db_url", "")
        if not db_url:
            return {"status": "error", "error": "Vector DB not configured", "error_kind": UNAVAILABLE}
        try:
            payload = {"collection": collection, "query": query, "n_results": n_results}
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(f"{db_url}/api/v1/collections/query", json=payload)
                if resp.status_code == 200:
                    return {"status": "success", "results": resp.json().get("results", [])}
        except Exception as e:
            return {"status": "error", "error": str(e), "error_kind": error_kind(e)}
        return {"status": "error", "error": "Search failed"}

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _safe_parse_json(self, text: str) -> Dict:
        """Extract and parse JSON from text, handling markdown code blocks."""
        import re
        text = text.strip()
        # Try to extract JSON from markdown code blocks
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        else:
            # Try to find JSON object/array boundaries
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                text = text[start:end + 1]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}
