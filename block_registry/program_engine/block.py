#!/usr/bin/env python3
"""Auto-generated adapter for Cerebrum block: program_engine.

The engine is the byte-identical mirror of the Factory's program kernel at
``app.blocks.program_engine``. This shim exposes it as a synchronous ``run()``
that dispatches one named operation; track content always arrives in the
caller's track.v1 document, never here.
"""

from app.blocks.program_engine import (
    backup,
    band,
    current_week,
    defense_prompt,
    graduated,
    jury_prompt,
    load_track,
    markdown,
    restore,
    session_prompt,
    sessions,
    total,
    week_start,
    weighted_average,
)


def run(**kwargs):
    """Execute one program-engine operation.

    ``input`` is ``{"operation": name, ...args}``. Returns the standardized
    block envelope ``{"status": "success"|"error", "result": ...}``.
    """
    input_data = kwargs.get("input", kwargs)
    if not isinstance(input_data, dict):
        return {"status": "error", "result": "input must be an object with 'operation'"}
    op = input_data.get("operation")
    try:
        if op == "load_track":
            return {
                "status": "success",
                "result": load_track(input_data["path"]).model_dump(mode="json"),
            }
        if op == "session_prompt":
            from app.blocks.program_engine import Session, Track

            track = Track.model_validate(input_data["track"])
            sess = Session(**input_data["session"])
            return {
                "status": "success",
                "result": session_prompt(track, input_data["week"], sess),
            }
        if op == "defense_prompt":
            from app.blocks.program_engine import Track

            return {
                "status": "success",
                "result": defense_prompt(
                    Track.model_validate(input_data["track"]), input_data["week"]
                ),
            }
        if op == "jury_prompt":
            from app.blocks.program_engine import Track

            return {
                "status": "success",
                "result": jury_prompt(Track.model_validate(input_data["track"])),
            }
        if op == "markdown":
            from app.blocks.program_engine import State, Track

            return {
                "status": "success",
                "result": markdown(
                    Track.model_validate(input_data["track"]),
                    State.model_validate(input_data["state"]),
                ),
            }
        if op == "restore":
            return {"status": "success", "result": restore(input_data["text"]).model_dump()}
    except Exception as exc:  # noqa: BLE001 — the envelope carries the reason
        return {"status": "error", "result": str(exc)}
    return {"status": "error", "result": f"unknown operation: {op!r}"}
