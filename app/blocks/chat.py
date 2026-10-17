"""Chat Block — Kimi (Moonshot) primary, template fallback.

Kimi is the platform's only LLM provider. The chat must never go completely
dark on the user, so:

1. **Kimi (Moonshot)** via the OpenAI-compatible cloud API when ``KIMI_API_KEY``
   (or ``MOONSHOT_API_KEY``) is set. Endpoint/model come from ``llm_config``
   (override with ``KIMI_BASE_URL`` / ``KIMI_MODEL``).
2. **Graceful template responder** — a deterministic, non-AI fallback that
   acknowledges the question, surfaces the reason the model layer is down, and
   points the operator at the env var that would restore it. This path always
   succeeds, so the chat never returns an unhandled error.

The block exposes a single ``provider`` field on the response so callers can
see which path served the answer (``kimi`` / ``offline_template``).
"""

import json
import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from app.core.typed_block import TypedBlock, Schema, ContentType


class ChatBlock(TypedBlock):
    """AI chat completions — Kimi (Moonshot) with a template fallback."""

    name = "chat"
    version = "3.0.0"
    description = "AI chat completions — Kimi (Moonshot) primary, template fallback"
    layer = 2
    tags = ["ai", "core", "llm", "chat", "typed"]
    requires = []

    default_config = {
        "default_provider": "kimi",
        "max_tokens": 2048,
        "temperature": 0.7,
    }

    accepted_input_types = ["Text", "TextContent", "ChatMessage"]
    produced_output_types = ["Text", "TextContent", "ChatMessage"]

    text_output_field = "text"

    input_schema = Schema(
        content_type=ContentType.TEXT,
        required_fields=[],
        optional_fields=["text", "message", "context"],
        format_hints={"max_length": 100000},
    )

    output_schema = Schema(
        content_type=ContentType.TEXT,
        required_fields=["text"],
        optional_fields=["provider", "model", "tokens", "status"],
        format_hints={},
    )

    ui_schema = {
        "input": {
            "type": "text",
            "accept": None,
            "placeholder": "Ask anything...",
            "multiline": True,
        },
        "output": {
            "type": "text",
            "fields": [
                {"name": "text", "type": "markdown", "label": "Response"},
            ],
        },
        "quick_actions": [
            {"icon": "💡", "label": "Explain", "prompt": "Explain this in simple terms"},
            {"icon": "📝", "label": "Summarize", "prompt": "Summarize the key points"},
        ],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        if isinstance(input_data, dict):
            message = (
                input_data.get("text")
                or input_data.get("content")
                or input_data.get("extracted_text")
                or str(input_data)
            )
        else:
            message = str(input_data)

        max_tokens = params.get("max_tokens", self.config.get("max_tokens", 2048))
        temperature = params.get("temperature", self.config.get("temperature", 0.7))
        stream = params.get("stream", False)
        model = params.get("model")  # None -> use Kimi default from llm_config

        system_prompt_text = self._resolve_system_prompt(input_data, params)

        use_rag = bool(
            params.get("use_rag")
            or (isinstance(input_data, dict) and input_data.get("use_rag"))
        )
        rag_project_id = (
            params.get("project_id")
            or (isinstance(input_data, dict) and input_data.get("project_id"))
        )
        if use_rag and rag_project_id:
            try:
                from app.core.rag.retriever import retrieve as _retrieve
                rag_k = int(params.get("rag_k", 5))
                chunks = await _retrieve(message, str(rag_project_id), k=rag_k)
                if chunks:
                    context = "\n\n".join(
                        f"[{c.doc_id}#{c.chunk_index}] {c.text}" for c in chunks
                    )
                    message = (
                        f"Relevant project context:\n{context}\n\n"
                        f"---\n\nUser question: {message}"
                    )
            except Exception as exc:  # noqa: BLE001
                _logging = logging.getLogger(__name__)
                _logging.warning(
                    "RAG retrieval failed for project %s: %s", rag_project_id, exc
                )

        from app.core.llm_config import _llm_config  # local import: avoid cycle at module load
        cfg = _llm_config()  # Kimi (Moonshot)

        api_key = os.getenv(cfg["env_key"]) if cfg["env_key"] else ""
        if api_key:
            effective_model = model or cfg["default_model"]
            extra_kwargs = {"system_prompt": system_prompt_text} if system_prompt_text else {}
            result = await self._call_cloud(
                message, effective_model, max_tokens, temperature, stream,
                api_key, cfg,
                **extra_kwargs,
            )
            if result.get("status") == "success":
                return result
            primary_error = result.get("error", "Kimi call failed")
        else:
            primary_error = f"{cfg['env_key']} not configured"

        return self._offline_template(message, primary_error)

    @staticmethod
    def _build_messages(message: str, system_prompt: Optional[str]) -> list:
        msgs = []
        if system_prompt and system_prompt.strip():
            msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "user", "content": message})
        return msgs

    def _resolve_system_prompt(
        self, input_data: Any, params: Dict
    ) -> Optional[str]:
        literal = None
        if isinstance(input_data, dict):
            literal = input_data.get("system_prompt")
        if not literal:
            literal = params.get("system_prompt")
        if isinstance(literal, str) and literal.strip():
            return literal

        fname = None
        if isinstance(input_data, dict):
            fname = input_data.get("system_prompt_file")
        if not fname:
            fname = params.get("system_prompt_file")
        if not fname:
            return None
        if not isinstance(fname, str):
            return None

        log = logging.getLogger(__name__)
        prompts_dir = (Path(__file__).parent.parent / "prompts").resolve()
        try:
            candidate = (prompts_dir / fname).resolve()
        except (OSError, ValueError) as exc:
            log.warning("system_prompt_file %r could not be resolved: %s", fname, exc)
            return None

        try:
            inside = candidate.is_relative_to(prompts_dir)
        except AttributeError:
            inside = str(candidate).startswith(str(prompts_dir) + os.sep)
        if not inside or candidate == prompts_dir:
            log.warning(
                "system_prompt_file %r rejected — resolves outside app/prompts/",
                fname,
            )
            return None
        if not candidate.is_file():
            log.warning(
                "system_prompt_file %r not found at %s", fname, candidate,
            )
            return None
        try:
            return candidate.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning(
                "system_prompt_file %r failed to read: %s", fname, exc,
            )
            return None

    async def _call_cloud(
        self,
        message: str,
        model: str,
        max_tokens: int,
        temperature: float,
        stream: bool,
        api_key: str,
        cfg: Dict[str, str],
        system_prompt: Optional[str] = None,
    ) -> Dict:
        url = cfg["url"]
        provider_name = cfg["provider"]
        messages = self._build_messages(message, system_prompt)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        if stream:
            async def _stream_generator():
                async with httpx.AsyncClient(timeout=60.0) as client:
                    async with client.stream(
                        "POST",
                        url,
                        headers=headers,
                        json={
                            "model": model,
                            "messages": messages,
                            "max_tokens": max_tokens,
                            "temperature": temperature,
                            "stream": True,
                        },
                    ) as response:
                        if response.status_code != 200:
                            err = await response.aread()
                            yield json.dumps({
                                "type": "error",
                                "message": f"{provider_name} error {response.status_code}: {err[:200]}",
                            })
                            return
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data = line[6:]
                            if data == "[DONE]":
                                continue
                            try:
                                chunk = json.loads(data)
                                content = chunk["choices"][0].get("delta", {}).get("content", "")
                                if content:
                                    yield content
                            except Exception:
                                continue

            return {
                "status": "success",
                "text": "",
                "provider": provider_name,
                "model": model,
                "stream": _stream_generator(),
            }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json={
                        "model": model,
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    },
                )
                if response.status_code != 200:
                    return {
                        "status": "error",
                        "error": f"{provider_name} API error (HTTP {response.status_code}): {response.text[:200]}",
                    }
                data = response.json()
                return {
                    "status": "success",
                    "text": data["choices"][0]["message"]["content"],
                    "provider": provider_name,
                    "model": model,
                    "tokens": data.get("usage", {}),
                }
        except httpx.TimeoutException:
            return {"status": "error", "error": f"{provider_name} request timed out"}
        except Exception as e:
            return {"status": "error", "error": f"{provider_name} failed: {e}"}


    def _offline_template(self, message: str, primary_error: str) -> Dict:
        snippet = (message or "").strip()
        if len(snippet) > 240:
            snippet = snippet[:237] + "..."
        body = (
            "**Chat is running in offline mode.**\n\n"
            "Kimi (the platform's language model) is not currently reachable, so I "
            "can't generate an AI response right now. Your message was received "
            "intact:\n\n"
            f"> {snippet or '(empty)'}\n\n"
            "**How to restore full chat:**\n"
            "- Set `KIMI_API_KEY` (or `MOONSHOT_API_KEY`) in `.env`.\n"
            "  Optionally override `KIMI_BASE_URL` / `KIMI_MODEL`.\n\n"
            f"_Kimi: {primary_error}_"
        )
        return {
            "status": "success",
            "text": body,
            "provider": "offline_template",
            "model": "template:v1",
            "primary_error": primary_error,
        }
