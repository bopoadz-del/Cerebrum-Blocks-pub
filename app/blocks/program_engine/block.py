"""ProgramEngineBlock — the Store entrypoint for the program kernel mirror.

The engine itself is the byte-identical mirror of the Factory's program kernel
in this package (schema, modes, calendar, rubric, prompts, export). This class
is the Store-side wrapper: it exposes the engine as a typed block.
"""

from __future__ import annotations

from typing import Any, Dict

from app.core.typed_block import ContentType, Schema, TypedBlock

from . import (
    defense_prompt,
    jury_prompt,
    load_track,
    markdown,
    restore,
    session_prompt,
)
from .calendar import Session
from .export import State
from .schema import Track


class ProgramEngineBlock(TypedBlock):
    name = "program_engine"
    version = "1.0.0"
    description = (
        "Runs any structured program: tracks, terms, weeks, sessions, rubric "
        "grading, calendar, faculty prompts"
    )
    layer = 3
    tags = ["domain", "program", "kernel", "calendar", "rubric", "prompts"]
    requires = []

    input_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=["operation"],
    )
    output_schema = Schema(content_type=ContentType.JSON)

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        data = input_data if isinstance(input_data, dict) else {}
        op = data.get("operation")
        try:
            if op == "load_track":
                return {
                    "status": "success",
                    "result": load_track(data["path"]).model_dump(mode="json"),
                }
            if op == "session_prompt":
                track = Track.model_validate(data["track"])
                sess = Session(**data["session"])
                return {
                    "status": "success",
                    "result": session_prompt(track, data["week"], sess),
                }
            if op == "defense_prompt":
                track = Track.model_validate(data["track"])
                return {
                    "status": "success",
                    "result": defense_prompt(track, data["week"]),
                }
            if op == "jury_prompt":
                track = Track.model_validate(data["track"])
                return {"status": "success", "result": jury_prompt(track)}
            if op == "markdown":
                track = Track.model_validate(data["track"])
                state = State.model_validate(data["state"])
                return {"status": "success", "result": markdown(track, state)}
            if op == "restore":
                return {"status": "success", "result": restore(data["text"]).model_dump()}
        except Exception as exc:  # noqa: BLE001 — the envelope carries the reason
            return {"status": "error", "error": str(exc)}
        return {"status": "error", "error": f"unknown operation: {op!r}"}
