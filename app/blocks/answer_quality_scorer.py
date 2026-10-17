"""Answer Quality Scorer — silent-failure detection, ported from <private-repo>
``level/scorers/silent_failure.py`` (the battery's Sev-1 scorer).

Ported exactly: status-line-as-answer (progress phrasing with nothing
left after the sentence), empty/too-short deliverable, scaffolding leaks
(tool-call markup reaching the reader), and truncation presented as
whole. The other scorers in the battery are not ported; this block ships
the silent-failure shape, which runs on every answer.
"""
from __future__ import annotations

import re
from typing import Any, Dict

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "answer_quality_scorer", "status": status, "result": result, "error": error, "detail": detail}


MINIMUM_ANSWER_CHARS = 12

_STATUS_LINE = re.compile(
    r"""(?ix)
    ^\W*(
        (?:i'?m\s+|i\s+am\s+|now\s+)?(?:processing|analysing|analyzing|working|
        searching|looking|generating|thinking|computing|reviewing|checking)\b
      | (?:analysis|processing|search|generation|task)\s+(?:complete|finished|done)\b
      | (?:done|complete|completed|finished|ok|okay|success)\b
      | (?:here\s+(?:is|are)\s+(?:the\s+)?(?:results?|answers?|details?))\b
      | please\s+wait\b
      | one\s+moment\b
    )
    [^.!?\n]*[.!?]?
    """
)

_SCAFFOLDING = re.compile(
    r"(?is)<\s*/?\s*(tool_call|function_call|thinking|scratchpad|system)\b"
    r"|```(?:tool|function)\b"
)

_TRUNCATED_TAIL = re.compile(r"[A-Za-z0-9,;:\-]\s*$")


def is_status_line(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    match = _STATUS_LINE.match(stripped)
    if match is None:
        return False
    remainder = stripped[match.end():].strip(" .\t\n\r")
    return len(remainder) < MINIMUM_ANSWER_CHARS


def looks_truncated(text: str) -> bool:
    stripped = (text or "").rstrip()
    if len(stripped) < MINIMUM_ANSWER_CHARS:
        return False
    if stripped.endswith(("…", "...")):
        return False
    return bool(_TRUNCATED_TAIL.search(stripped))


class AnswerQualityScorerBlock(UniversalBlock):
    """Silent-failure scoring ported from <private-repo>."""

    name = "answer_quality_scorer"
    version = "1.0.0"
    description = (
        "Silent-failure scorer ported from <private-repo> level/scorers/silent_failure.py: "
        "status-line-as-answer, empty or too-short deliverable, scaffolding leaks, "
        "and truncation presented as whole. Runs on every answer; the battery's "
        "other scorers are not ported."
    )
    layer = 3
    tags = ["eval", "quality", "silent-failure", "the-level"]
    requires = []

    default_config = {"minimum_answer_chars": MINIMUM_ANSWER_CHARS}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "score", "answered": true, "response": "Processing your request…"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "score")).lower()
        try:
            if action == "score":
                return self._score(payload)
            if action == "is_status_line":
                return _envelope("ok", {"is_status_line": is_status_line(str(payload.get("text", "")))})
            if action == "looks_truncated":
                return _envelope("ok", {"looks_truncated": looks_truncated(str(payload.get("text", "")))})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["score", "is_status_line", "looks_truncated"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    def _score(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        answered = bool(payload.get("answered", True))
        response = str(payload.get("response") or "")
        stripped = response.strip()
        verdict = "pass"
        reasons: list = []
        failure_class = None
        if not answered:
            return _envelope("ok", {"verdict": "not_applicable", "reasons": ["the turn reported its failure, which is a reported failure rather than a silent one"]})
        if not stripped:
            verdict = "fail"
            failure_class = "silent_failure"
            reasons.append("the target returned an empty response and reported success")
        elif len(stripped) < MINIMUM_ANSWER_CHARS:
            verdict = "fail"
            failure_class = "silent_failure"
            reasons.append(f"the response is {len(stripped)} characters, which is not an answer to anything")
        elif is_status_line(stripped):
            verdict = "fail"
            failure_class = "silent_failure"
            reasons.append("the response is a status line, not an answer; the pipeline ran, something came back, and the reader has nothing")
        if _SCAFFOLDING.search(stripped):
            verdict = "fail"
            failure_class = "format_leak"
            reasons.append("scaffolding leaked into the answer (tool-call markup reached the reader)")
        if looks_truncated(stripped):
            verdict = "fail"
            failure_class = "truncated"
            reasons.append("the answer stops mid-thought and nothing says so")
        return _envelope("ok", {"verdict": verdict, "reasons": reasons, "failure_class": failure_class})
