"""CPM Engine block - roadmap-named wrapper over the CPM library, ported
from The_Fork ``app/blocks/cpm_engine.py``.

The real forward/backward pass, float, and critical-path logic lives in
``app.lib.pm_computations.compute_cpm`` - a wholesale, verbatim port of
The_Fork's ``app/lib/pm_computations.py`` (already present in this store,
byte-identical to the donor) with its Pydantic schemas
(``app/schemas/cpm.py``, byte-identical to the donor). This block is the
donor's thin wrapper over that library, plus actions for the library's own
pure functions: resource histogram, gantt bars, schedule compression, the
Primavera XER tokenizer/parser, look-ahead windowing and the schedule
Excel writer (``app/lib/excel_templates.py`` ported alongside).
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "cpm_engine",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


class CpmEngineBlock(UniversalBlock):
    auto_validate = False
    name = "cpm_engine"
    version = "1.0.0"
    description = (
        "real (clone of The_Fork app/blocks/cpm_engine.py + app/lib/"
        "pm_computations.py): Critical Path Method engine - ES/EF/LS/LF, "
        "total/free float, critical path, resource histograms, schedule "
        "compression, Primavera P6 XER parsing, look-ahead windowing and "
        "schedule Excel export. Circular-dependency detection refuses a "
        "cycle instead of computing nonsense; an unknown activity id is "
        "refused. Pure computation, no AI, no network."
    )
    layer = 3
    tags = ["construction", "schedule", "cpm", "critical-path", "primavera", "the-fork"]
    requires = []

    default_config = {
        "calendar_work_weekdays": [0, 1, 2, 3, 4],
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"action": "compute", "activities": [{"id": "A", "duration": 5, "predecessors": []}]}',
            "multiline": True,
        },
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        action = str(data.get("action") or params.get("action") or "compute").lower()
        try:
            if action == "compute":
                return self._compute(data, params)
            if action == "histogram":
                return self._histogram(data, params)
            if action == "gantt":
                return self._gantt(data, params)
            if action == "compress":
                return self._compress(data, params)
            if action == "parse_xer":
                return self._parse_xer(data, params)
            if action == "parse_xer_full":
                return self._parse_xer(data, params, full=True)
            if action == "lookahead":
                return self._lookahead(data, params)
            if action == "write_excel":
                return self._write_excel(data, params)
            return _envelope(
                "error", error=f"unknown action: {action}",
                detail={"known": ["compute", "histogram", "gantt", "compress",
                                  "parse_xer", "parse_xer_full", "lookahead", "write_excel"]},
            )
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("failed", error=f"{type(exc).__name__}: {exc}")

    # -- helpers ----------------------------------------------------------
    def _build_input(self, activities: List[Any], project_start: Any = None):
        from app.schemas.cpm import Activity, CPMInput, WorkCalendar

        cpm_activities = [
            Activity(**a) if isinstance(a, dict) else a for a in activities
        ]
        cal = WorkCalendar(
            work_weekdays=self.config.get("calendar_work_weekdays", [0, 1, 2, 3, 4])
        )
        return CPMInput(
            activities=cpm_activities, project_start=project_start, calendar=cal
        )

    @staticmethod
    def _output_dict(output) -> Dict[str, Any]:
        return {
            "project_duration": output.project_duration,
            "project_finish": output.project_finish.isoformat() if output.project_finish else None,
            "critical_path": output.critical_path,
            "critical_percentage": output.critical_percentage,
            "near_critical": output.near_critical,
            "results": [r.model_dump(mode="json") for r in output.results],
        }

    # -- actions ----------------------------------------------------------
    def _compute(self, data: Dict, params: Dict) -> Dict:
        from app.lib.pm_computations import compute_cpm

        activities = data.get("activities") or params.get("activities") or []
        if not activities:
            return _envelope("refused", error="No activities provided")
        project_start = data.get("project_start") or params.get("project_start")
        output = compute_cpm(self._build_input(activities, project_start))
        return _envelope("ok", self._output_dict(output))

    def _histogram(self, data: Dict, params: Dict) -> Dict:
        from app.lib.pm_computations import resource_histogram

        activities = data.get("activities") or params.get("activities") or []
        if not activities:
            return _envelope("refused", error="No activities provided")
        cpm_input = self._build_input(activities)
        from app.lib.pm_computations import compute_cpm

        output = compute_cpm(cpm_input)
        histogram = resource_histogram(
            output.results,
            cpm_input.activities,
            period_unit=str(data.get("period_unit") or "week"),
            task_resources=data.get("task_resources"),
        )
        return _envelope("ok", histogram.model_dump(mode="json"))

    def _gantt(self, data: Dict, params: Dict) -> Dict:
        from app.lib.pm_computations import compute_cpm, gantt_data

        activities = data.get("activities") or params.get("activities") or []
        if not activities:
            return _envelope("refused", error="No activities provided")
        output = compute_cpm(self._build_input(activities))
        bars = [b.model_dump(mode="json") for b in gantt_data(output.results)]
        return _envelope("ok", {"bars": bars})

    def _compress(self, data: Dict, params: Dict) -> Dict:
        from app.lib.pm_computations import compress_schedule

        activities = data.get("activities") or params.get("activities") or []
        reductions = data.get("reductions") or {}
        if not activities:
            return _envelope("refused", error="No activities provided")
        if not isinstance(reductions, dict):
            return _envelope("refused", error="reductions must be {activity_id: days}")
        revised, delta = compress_schedule(
            self._build_input(activities), {str(k): int(v) for k, v in reductions.items()}
        )
        return _envelope("ok", {"days_saved": delta, **self._output_dict(revised)})

    def _parse_xer(self, data: Dict, params: Dict, full: bool = False) -> Dict:
        from app.lib.pm_computations import parse_xer, parse_xer_full

        text = data.get("text") or params.get("text") or ""
        if not text or not str(text).strip():
            return _envelope("refused", error="parse_xer needs the .xer text blob")
        if full:
            bundle = parse_xer_full(str(text))
            bundle["activities"] = [a.model_dump(mode="json") for a in bundle["activities"]]
            return _envelope("ok", bundle)
        activities = parse_xer(str(text))
        return _envelope("ok", {"activities": [a.model_dump(mode="json") for a in activities]})

    def _lookahead(self, data: Dict, params: Dict) -> Dict:
        from app.lib.pm_computations import select_look_ahead

        activities = data.get("activities") or params.get("activities") or []
        as_of = data.get("as_of")
        window_days = int(
            data.get("window_days")
            if data.get("window_days") is not None
            else 21
        )
        try:
            result = select_look_ahead(
                activities,
                as_of=date.fromisoformat(as_of) if as_of else None,
                window_days=window_days,
            )
        except ValueError as exc:
            return _envelope("refused", error=str(exc))
        return _envelope("ok", result)

    def _write_excel(self, data: Dict, params: Dict) -> Dict:
        from app.lib.pm_computations import compute_cpm, write_schedule_excel

        path = data.get("path") or params.get("path")
        if not path:
            return _envelope("refused", error="write_excel needs an output path")
        activities = data.get("activities") or params.get("activities") or []
        if not activities:
            return _envelope("refused", error="No activities provided")
        output = compute_cpm(self._build_input(activities))
        write_schedule_excel(output, str(path))
        return _envelope("ok", {"path": str(path)})
