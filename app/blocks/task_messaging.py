"""Task Messaging - deterministic participant-scoped message threads.

In-app chat between the parties of a task (customer, provider, platform),
scoped to a task entity: thread creation, participant-gated sends, message
listing with after-cursors, moderation flags, and an evidence bundle for
disputes (deterministic digests, no timestamps invented). Not an LLM block:
this is message-thread state and rules; the existing `chat` block owns
generative conversation and is untouched.

Pure Python: no network, no filesystem. Messages are refused unless the
sender is a participant; blocklisted terms are refused in strict mode and
flagged otherwise.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

MAX_MESSAGE_LENGTH = 4000
DEFAULT_BLOCKLIST = ["fraud", "scam"]


class TaskMessagingBlock(UniversalBlock):
    """Deterministic task-scoped messaging with participant gates."""

    name = "task_messaging"
    version = "1.0.0"
    description = (
        "Deterministic task-scoped message threads: thread creation, "
        "participant-gated sends, moderation flags, after-cursor listing, "
        "and dispute-ready evidence bundles. Not an LLM block; generative "
        "conversation stays with the `chat` block."
    )
    layer = 3
    tags = ["domain", "marketplace", "task", "messaging", "deterministic"]
    requires: List[str] = []
    author = "Cerebrum Team"
    default_config: Dict[str, Any] = {
        "blocklist": list(DEFAULT_BLOCKLIST),
        "strict_moderation": False,
        "max_message_length": MAX_MESSAGE_LENGTH,
    }
    ui_schema = {
        "input": {"type": "json"},
        "output": {"type": "json"},
        "params": [],
        "quick_actions": [],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        # thread_id -> {"task_id": str, "participants": [str], "messages": [...], "seq": int}
        self.threads: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ api
    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**params, **data}
        operation = merged.get("operation") or merged.get("action") or "thread"

        try:
            if operation == "thread":
                return self._thread(merged)
            if operation == "send":
                return self._send(merged)
            if operation == "list":
                return self._list(merged)
            if operation == "evidence":
                return self._evidence(merged)
            if operation == "status":
                return self._status(merged)
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc), "operation": operation}

        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": ["thread", "send", "list", "evidence", "status"],
        }

    # -------------------------------------------------------------- helpers
    def _require(self, data: Dict[str, Any], keys: List[str]) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                return key
        return None

    def _check_moderation(self, text: str) -> List[str]:
        blocklist = self.config.get("blocklist") or DEFAULT_BLOCKLIST
        lowered = text.lower()
        return [term for term in blocklist if term and term.lower() in lowered]

    # ----------------------------------------------------------- operations
    def _thread(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["task_id", "participants"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        participants = data["participants"]
        if not isinstance(participants, list) or len(participants) < 2:
            return {"status": "error", "error": "participants: at least two required"}
        thread_id = data.get("thread_id") or f"thread:{data['task_id']}"
        existing = self.threads.get(thread_id)
        if existing is not None:
            return {**existing["public"], "idempotent": True}
        record = {
            "task_id": data["task_id"],
            "participants": [p for p in participants],
            "messages": [],
            "seq": 0,
        }
        public = {
            "status": "success",
            "operation": "thread",
            "thread_id": thread_id,
            "task_id": data["task_id"],
            "participants": record["participants"],
        }
        record["public"] = public
        self.threads[thread_id] = record
        return public

    def _send(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["thread_id", "sender", "body"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        thread = self.threads.get(data["thread_id"])
        if thread is None:
            return {"status": "error", "error": "thread_not_found", "thread_id": data["thread_id"]}
        if data["sender"] not in thread["participants"]:
            return {
                "status": "error",
                "error": "sender_not_participant",
                "participants": thread["participants"],
            }
        body = data["body"]
        if not isinstance(body, str) or not body.strip():
            return {"status": "error", "error": "body: non-empty string required"}
        if len(body) > (self.config.get("max_message_length") or MAX_MESSAGE_LENGTH):
            return {"status": "error", "error": "body_too_long"}

        flags = self._check_moderation(body)
        if flags and (self.config.get("strict_moderation")):
            return {"status": "error", "error": "message_refused_blocklist", "flags": flags}

        thread["seq"] += 1
        message = {
            "seq": thread["seq"],
            "sender": data["sender"],
            "body": body,
            "flagged": bool(flags),
            "flags": flags,
        }
        thread["messages"].append(message)
        return {
            "status": "success",
            "operation": "send",
            "thread_id": data["thread_id"],
            "seq": message["seq"],
            "flagged": message["flagged"],
            "flags": message["flags"],
        }

    def _list(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["thread_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        thread = self.threads.get(data["thread_id"])
        if thread is None:
            return {"status": "error", "error": "thread_not_found", "thread_id": data["thread_id"]}
        messages = thread["messages"]
        after = data.get("after")
        if after is not None:
            try:
                after = int(after)
            except (TypeError, ValueError):
                return {"status": "error", "error": "after: must be an integer"}
            messages = [m for m in messages if m["seq"] > after]
        limit = data.get("limit")
        if limit is not None:
            try:
                limit = int(limit)
            except (TypeError, ValueError):
                return {"status": "error", "error": "limit: must be an integer"}
            messages = messages[:limit]
        return {
            "status": "success",
            "operation": "list",
            "thread_id": data["thread_id"],
            "messages": messages,
            "count": len(messages),
            "next_after": messages[-1]["seq"] if messages else None,
        }

    def _evidence(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["thread_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        thread = self.threads.get(data["thread_id"])
        if thread is None:
            return {"status": "error", "error": "thread_not_found", "thread_id": data["thread_id"]}
        bundle = {
            "thread_id": data["thread_id"],
            "task_id": thread["task_id"],
            "participants": thread["participants"],
            "messages": thread["messages"],
        }
        digest = hashlib.sha256(
            json.dumps(bundle, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return {
            "status": "success",
            "operation": "evidence",
            "thread_id": data["thread_id"],
            "digest": digest,
            "message_count": len(thread["messages"]),
            "bundle": bundle,
        }

    def _status(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["thread_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        thread = self.threads.get(data["thread_id"])
        if thread is None:
            return {"status": "error", "error": "thread_not_found", "thread_id": data["thread_id"]}
        return {
            "status": "success",
            "operation": "status",
            "thread_id": data["thread_id"],
            "task_id": thread["task_id"],
            "participants": thread["participants"],
            "message_count": len(thread["messages"]),
        }
