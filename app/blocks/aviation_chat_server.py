"""Aviation Chat Server — WebSocket transport block.

Scope (enforced in code):
- READS: authenticated session, inbound user messages
- WRITES: WebSocket stream frames out; session/conversation state to memory block only
- NEVER: calls the LLM or tools directly (routes through orchestrator);
  never bypasses auth; never persists corpus data.
- RULE: pure streaming transport — carries messages, holds no domain logic;
  induced failure surfaces a visible error frame, never a silent stall.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from app.core.grounding import VERDICT_OUT_OF_SCOPE, check_scope_refusal, persist_verdict
from app.core.typed_block import TypedBlock, Schema, ContentType


logger = logging.getLogger(__name__)


class AviationChatServerBlock(TypedBlock):
    """WebSocket transport layer for the aviation conversational agent.

    The block does not contain domain logic.  It:
      1. Validates that the session is authenticated.
      2. Loads the conversation history from the memory block.
      3. Routes the user message through the orchestrator (retrieval + generation + grounding gate).
      4. Emits stream frames and persists only session state back to memory.
    """

    name = "aviation_chat_server"
    version = "1.0.0"
    description = (
        "WebSocket transport for the aviation agent. Routes every message "
        "through the orchestrator and streams frames back."
    )
    layer = 2
    tags = ["aviation", "chat", "transport", "websocket", "streaming"]
    requires = ["memory", "orchestrator"]

    input_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=["session_id", "message"],
        optional_fields=[
            "user",
            "project_id",
            "auth_token",
            "conversation",
            "stream",
        ],
        format_hints={},
    )

    output_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=["status", "frames"],
        optional_fields=[
            "session_id",
            "error",
            "memory_stored",
            "conversation_length",
        ],
        format_hints={},
    )

    default_config = {
        "require_auth": True,
        "max_history": 50,
        "memory_ttl": 86400,
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"session_id": "...", "message": "...", "project_id": "..."}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "status", "type": "text", "label": "Status"},
                {"name": "frames", "type": "json", "label": "Stream Frames"},
            ],
        },
        "quick_actions": [
            {"icon": "✈️", "label": "Send aviation message", "prompt": "Send a message to the aviation agent."},
        ],
    }

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}

        session_id = data.get("session_id") or params.get("session_id")
        message = data.get("message") or params.get("message")
        user = data.get("user") or params.get("user")
        project_id = data.get("project_id") or params.get("project_id")
        auth_token = data.get("auth_token") or params.get("auth_token")
        stream = bool(data.get("stream", params.get("stream", True)))

        if not session_id:
            return self._error_frame("Missing session_id.", session_id=None)
        if not message:
            return self._error_frame("Missing message.", session_id=session_id)

        if self.config.get("require_auth", True) and not auth_token:
            return self._error_frame(
                "Authentication required.", session_id=session_id, status_code=401
            )

        # Scope refusal precedes everything: a refused question never
        # reaches the orchestrator or the LLM.
        refusal = check_scope_refusal(str(message))
        if refusal is not None:
            persist_verdict(
                {
                    "surface": "aviation_chat_server",
                    "session_id": session_id,
                    "query": str(message)[:500],
                    "verdict": VERDICT_OUT_OF_SCOPE,
                    "refusal_id": refusal["id"],
                }
            )
            return {
                "status": "success",
                "session_id": session_id,
                "frames": [
                    {
                        "type": "error",
                        "payload": {
                            "verdict": VERDICT_OUT_OF_SCOPE,
                            "reason": refusal["reason"],
                        },
                        "timestamp": time.time(),
                    },
                    {
                        "type": "done",
                        "payload": {"verdict": VERDICT_OUT_OF_SCOPE},
                        "timestamp": time.time(),
                    },
                ],
                "memory_stored": False,
                "conversation_length": 0,
            }

        # Load or initialise conversation history.
        conversation = await self._load_conversation(session_id, data)

        # Append the user message.
        user_turn = {
            "role": "user",
            "content": str(message),
            "project_id": project_id,
            "timestamp": time.time(),
        }
        conversation.append(user_turn)
        conversation = conversation[-self.config.get("max_history", 50) :]

        # Route through orchestrator.  This block never calls an LLM or tool directly.
        try:
            orchestrator_result = await self._call_orchestrator(
                message=message,
                conversation=conversation,
                project_id=project_id,
                user=user,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Aviation chat orchestrator failed for session %s", session_id)
            return self._error_frame(
                f"Agent processing failed: {exc}", session_id=session_id
            )

        # Persist the verdict to the grounding audit store — every answer,
        # every time, including blocks.
        grounding = orchestrator_result.get("grounding") or {}
        persist_verdict(
            {
                "surface": "aviation_chat_server",
                "session_id": session_id,
                "query": str(message)[:500],
                "verdict": grounding.get("verdict"),
                "blocked_reason": grounding.get("blocked_reason"),
            }
        )

        # Build stream frames from the orchestrator output.
        frames = self._build_frames(orchestrator_result, stream=stream)

        # Append assistant turn if a grounded response was produced.
        assistant_text = self._extract_assistant_text(orchestrator_result)
        if assistant_text:
            conversation.append({
                "role": "assistant",
                "content": assistant_text,
                "timestamp": time.time(),
                "grounding": orchestrator_result.get("grounding"),
            })

        # Persist only session/conversation state — never corpus data.
        memory_result = await self._save_conversation(session_id, conversation)

        return {
            "status": "success",
            "session_id": session_id,
            "frames": frames,
            "memory_stored": memory_result.get("stored", False),
            "conversation_length": len(conversation),
        }

    # ------------------------------------------------------------------
    # Frame helpers
    # ------------------------------------------------------------------

    def _build_frames(self, orchestrator_result: Dict, *, stream: bool) -> List[Dict]:
        """Convert orchestrator output into visible stream frames."""
        frames: List[Dict] = []

        if not stream:
            frames.append({
                "type": "complete",
                "payload": orchestrator_result,
                "timestamp": time.time(),
            })
            return frames

        # Streaming path: emit status, chunks, grounding, and final answer frames.
        grounding = orchestrator_result.get("grounding") or {}
        verdict = grounding.get("verdict")
        allowed_response = grounding.get("allowed_response")
        blocked_reason = grounding.get("blocked_reason")

        frames.append({"type": "status", "payload": "retrieving", "timestamp": time.time()})
        frames.append({"type": "status", "payload": "grounding", "timestamp": time.time()})

        if verdict == "block":
            frames.append({
                "type": "error",
                "payload": blocked_reason or "Answer blocked by aviation grounding gate.",
                "timestamp": time.time(),
            })
        elif allowed_response:
            frames.append({
                "type": "delta",
                "payload": allowed_response,
                "timestamp": time.time(),
            })
            frames.append({
                "type": "grounding",
                "payload": grounding,
                "timestamp": time.time(),
            })
        else:
            frames.append({
                "type": "error",
                "payload": orchestrator_result.get("error") or "No response produced.",
                "timestamp": time.time(),
            })

        frames.append({"type": "done", "payload": {"verdict": verdict}, "timestamp": time.time()})
        return frames

    def _extract_assistant_text(self, orchestrator_result: Dict) -> Optional[str]:
        grounding = orchestrator_result.get("grounding") or {}
        return grounding.get("allowed_response") or orchestrator_result.get("answer")

    def _error_frame(
        self, error: str, session_id: Optional[str] = None, status_code: int = 500
    ) -> Dict:
        """Return a visible error envelope — never a silent empty success."""
        return {
            "status": "error",
            "session_id": session_id,
            "frames": [
                {
                    "type": "error",
                    "payload": error,
                    "status_code": status_code,
                    "timestamp": time.time(),
                }
            ],
            "memory_stored": False,
            "conversation_length": 0,
            "error": error,
        }

    # ------------------------------------------------------------------
    # Memory integration
    # ------------------------------------------------------------------

    async def _load_conversation(
        self, session_id: str, data: Dict
    ) -> List[Dict]:
        """Load conversation history from the memory block or inline payload."""
        inline = data.get("conversation")
        if isinstance(inline, list):
            return list(inline)

        memory = await self._resolve_memory_block()
        if memory is None:
            return []

        try:
            result = await memory.process(
                {"action": "get", "key": f"conversation:{session_id}"},
                params={},
            )
            value = result.get("value") if isinstance(result, dict) else None
            if isinstance(value, list):
                return value
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load conversation from memory: %s", exc)

        return []

    async def _save_conversation(
        self, session_id: str, conversation: List[Dict]
    ) -> Dict:
        """Persist conversation state to the memory block only."""
        memory = await self._resolve_memory_block()
        if memory is None:
            return {"stored": False, "reason": "memory_block_unavailable"}

        try:
            return await memory.process(
                {
                    "action": "set",
                    "key": f"conversation:{session_id}",
                    "value": conversation,
                    "ttl": self.config.get("memory_ttl", 86400),
                },
                params={},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save conversation to memory: %s", exc)
            return {"stored": False, "reason": str(exc)}

    async def _resolve_memory_block(self) -> Optional[Any]:
        """Resolve the memory block via wired dependency or HAL."""
        dep = self.get_dep("memory")
        if dep is not None:
            return dep
        if self.hal is not None:
            try:
                return await self.hal.get_block("memory")
            except Exception as exc:  # noqa: BLE001
                logger.warning("HAL memory resolution failed: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Orchestrator integration
    # ------------------------------------------------------------------

    async def _call_orchestrator(
        self,
        message: str,
        conversation: List[Dict],
        project_id: Optional[str],
        user: Optional[str],
    ) -> Dict:
        """Hand the user message to the orchestrator; do not call LLM/tools directly.

        The step chain is always the server-defined default: callers cannot
        supply their own steps, so the grounding gate can never be omitted.
        """
        orchestrator = await self._resolve_orchestrator()
        if orchestrator is None:
            raise RuntimeError("Orchestrator block is not available.")

        steps = self._default_steps(project_id)
        payload = {
            "steps": steps,
            "initial_input": {
                "query": message,
                "conversation": conversation,
                "project_id": project_id,
                "user": user,
            },
        }

        result = await orchestrator.process(payload, params={})
        # Normalise the result so downstream frame builders see a stable shape.
        return self._normalise_orchestrator_result(result, message)

    async def _resolve_orchestrator(self) -> Optional[Any]:
        """Resolve the orchestrator block via wired dependency or HAL."""
        dep = self.get_dep("orchestrator")
        if dep is not None:
            return dep
        if self.hal is not None:
            try:
                return await self.hal.get_block("orchestrator")
            except Exception as exc:  # noqa: BLE001
                logger.warning("HAL orchestrator resolution failed: %s", exc)
        return None

    def _default_steps(self, project_id: Optional[str]) -> List[Dict]:
        """Default aviation agent chain: retrieve, generate, ground."""
        steps: List[Dict] = [
            {
                "block": "vector_search",
                "params": {
                    "operation": "search",
                    "collection": project_id or "aviation_default",
                    "query": "{{initial_input.query}}",
                },
            },
            {
                "block": "chat",
                "params": {
                    "text": "{{initial_input.query}}",
                    "context": "{{steps.0.output.results}}",
                    "system_prompt": (
                        "You are an aviation operations assistant. Answer using ONLY "
                        "the retrieved context. Do not fabricate fares, weights, fuel, "
                        "or capacities. Cite your sources."
                    ),
                },
            },
            {
                "block": "aviation_grounding_gate",
                "params": {
                    "query": "{{initial_input.query}}",
                    "answer": "{{steps.1.output.text}}",
                    "citations": "{{steps.0.output.results}}",
                },
            },
        ]
        return steps

    def _normalise_orchestrator_result(self, result: Any, query: str) -> Dict:
        """Extract grounding and answer fields from various orchestrator shapes."""
        if not isinstance(result, dict):
            return {"error": "Orchestrator returned non-dict result.", "answer": None}

        final_output = result.get("final_output", result)
        if not isinstance(final_output, dict):
            final_output = {"text": str(final_output)}

        grounding = final_output.get("grounding") or final_output
        if isinstance(grounding, dict) and "verdict" in grounding:
            # The gate's allowed_response is the ONLY releasable text — a
            # blocked verdict must never fall back to the raw draft.
            return {
                "answer": grounding.get("allowed_response"),
                "grounding": grounding,
            }

        # No verdict produced → fail closed. A verdict is never fabricated.
        return {
            "answer": None,
            "grounding": {
                "verdict": "block",
                "allowed_response": None,
                "blocked_reason": "orchestrator produced no grounding verdict",
            },
        }
