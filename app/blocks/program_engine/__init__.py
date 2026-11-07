"""Program Kernel — a structured program engine (tracks, terms, weeks, sessions,
rubric grading, calendar, faculty prompts, export).

The content (tracks, themes, readings, cases, deliverables) lives in the
domain packs under ``app/factory/standards/domain_packs/executive_programs/``,
never in this package. This package is the engine: schema, calendar, rubric,
modes, prompts and export.
"""

from .calendar import Session, current_week, sessions, week_start
from .export import RestoreError, State, WeekState, backup, markdown, restore
from .modes import MODE_BY_KIND, MODE_TEXT, SessionMode, mode_for_kind
from .prompts import defense_prompt, jury_prompt, session_prompt
from .rubric import band, graduated, total, weighted_average
from .schema import (
    Case,
    Criterion,
    Deliverable,
    Reading,
    Rubric,
    Term,
    Track,
    TrackError,
    Week,
    Weights,
    load_track,
)

__all__ = [
    "Reading",
    "Case",
    "Deliverable",
    "Week",
    "Term",
    "Criterion",
    "Rubric",
    "Weights",
    "Track",
    "TrackError",
    "load_track",
    "Session",
    "SessionMode",
    "MODE_BY_KIND",
    "MODE_TEXT",
    "mode_for_kind",
    "week_start",
    "sessions",
    "current_week",
    "total",
    "band",
    "weighted_average",
    "graduated",
    "session_prompt",
    "defense_prompt",
    "jury_prompt",
    "State",
    "WeekState",
    "RestoreError",
    "markdown",
    "backup",
    "restore",
]


class ProgramEngineBlock:
    """Runs any structured program: tracks, terms, weeks, sessions, rubric
    grading, calendar, faculty prompts. All track content arrives in the
    caller's track.v1 document — nothing is hardwired here."""

    def run(self, **kwargs):
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
                track = Track.model_validate(input_data["track"])
                sess = Session(**input_data["session"])
                return {"status": "success", "result": session_prompt(track, input_data["week"], sess)}
            if op == "defense_prompt":
                return {"status": "success", "result": defense_prompt(Track.model_validate(input_data["track"]), input_data["week"])}
            if op == "jury_prompt":
                return {"status": "success", "result": jury_prompt(Track.model_validate(input_data["track"]))}
            if op == "markdown":
                return {"status": "success", "result": markdown(Track.model_validate(input_data["track"]), State.model_validate(input_data["state"]))}
            if op == "restore":
                return {"status": "success", "result": restore(input_data["text"]).model_dump()}
        except Exception as exc:  # noqa: BLE001 — the envelope carries the reason
            return {"status": "error", "result": str(exc)}
        return {"status": "error", "result": f"unknown operation: {op!r}"}
