# Ported (real) from <private-repo> src/<private-repo>/schedule_4d.py (donor HEAD on disk).
# Intra-package imports are rewritten to relative imports; the code is
# otherwise carried verbatim. DEXPI ingestion is NOT duplicated here: the
# Store's dexpi_ingest block (ported from ingest_dexpi.py) covers ingestion,
# and this package carries the downstream digital thread (graph, routing,
# tables, clash, schedule 4D, generators, PCF, maturity, cascade, exporters).
# The agent/API layers (agent_tools, cli, server, mcp_server) are not ported.
"""4D schedule: CSV/JSON import, co-activity clash, look-ahead + discipline filters."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Union

from .graph import TopologyGraph
from .models import DesignVolume, Discipline, ScheduleActivity, WorkPackage

# Disciplines commonly used in look-ahead filters
LOOKAHEAD_DISCIPLINES = ("PIP", "INS", "ELE", "TEL", "EQP", "STR", "CIV")


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {value}")


def volumes_adjacent(a: DesignVolume, b: DesignVolume, gap_m: float = 2.0) -> bool:
    """True if AABB touch or centres within gap_m (soft co-activity)."""
    # expand a by gap and test overlap with b
    return not (
        a.xmax + gap_m < b.xmin
        or b.xmax + gap_m < a.xmin
        or a.ymax + gap_m < b.ymin
        or b.ymax + gap_m < a.ymin
        or a.zmax + gap_m < b.zmin
        or b.zmax + gap_m < a.zmin
    )


class Schedule4D:
    """Holds activities and co-activity / look-ahead logic."""

    def __init__(self, graph: Optional[TopologyGraph] = None) -> None:
        self.graph = graph
        self.activities: dict[str, ScheduleActivity] = {}
        self.schedule_date: date = date.today()

    def set_schedule_date(self, d: Union[str, date]) -> None:
        self.schedule_date = _parse_date(d)

    def add_activity(self, activity: ScheduleActivity) -> None:
        self.activities[activity.id] = activity

    def load_json(self, source: Union[str, Path, dict[str, Any], list[Any]]) -> int:
        if isinstance(source, (str, Path)):
            path = Path(source)
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = source
        if isinstance(data, dict):
            if "schedule_date" in data:
                self.set_schedule_date(data["schedule_date"])
            items = data.get("activities", data.get("tasks", [])) or []
        else:
            items = data
        count = 0
        for item in items:
            disc = item.get("discipline")
            activity = ScheduleActivity(
                id=item["id"],
                name=item.get("name", item["id"]),
                wp_id=item.get("wp_id"),
                discipline=Discipline(disc) if disc else None,
                start=_parse_date(item["start"]),
                finish=_parse_date(item["finish"]),
                man_hours=item.get("man_hours"),
                status=item.get("status", "planned"),
            )
            self.add_activity(activity)
            count += 1
            if self.graph and activity.wp_id and activity.wp_id in self.graph.work_packages:
                wp = self.graph.work_packages[activity.wp_id]
                wp.start = activity.start
                wp.finish = activity.finish
        return count

    def load_csv(self, source: Union[str, Path]) -> int:
        path = Path(source)
        count = 0
        with path.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                disc = row.get("discipline") or None
                activity = ScheduleActivity(
                    id=row["id"],
                    name=row.get("name") or row["id"],
                    wp_id=row.get("wp_id") or None,
                    discipline=Discipline(disc) if disc else None,
                    start=_parse_date(row["start"]),
                    finish=_parse_date(row["finish"]),
                    man_hours=float(row["man_hours"]) if row.get("man_hours") else None,
                    status=row.get("status") or "planned",
                )
                self.add_activity(activity)
                count += 1
                if self.graph and activity.wp_id and activity.wp_id in self.graph.work_packages:
                    wp = self.graph.work_packages[activity.wp_id]
                    wp.start = activity.start
                    wp.finish = activity.finish
        return count

    @staticmethod
    def _ranges_overlap(a_start: date, a_finish: date, b_start: date, b_finish: date) -> bool:
        return a_start <= b_finish and b_start <= a_finish

    def co_activity_check(
        self,
        work_packages: Optional[list[WorkPackage]] = None,
        disciplines: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Flag WPs that overlap in time AND share the same design volume."""
        if work_packages is None:
            if self.graph is None:
                work_packages = []
            else:
                work_packages = list(self.graph.work_packages.values())

        for act in self.activities.values():
            if act.wp_id and self.graph and act.wp_id in self.graph.work_packages:
                wp = self.graph.work_packages[act.wp_id]
                if wp.start is None:
                    wp.start = act.start
                if wp.finish is None:
                    wp.finish = act.finish

        disc_filter = {d.upper() for d in disciplines} if disciplines else None

        flagged: list[dict[str, Any]] = []
        wps = [wp for wp in work_packages if wp.start and wp.finish]
        if disc_filter:
            wps = [wp for wp in wps if wp.discipline.value in disc_filter]

        volume_index: dict[str, dict[str, Any]] = {}
        if self.graph:
            for vid, vol in self.graph.volumes.items():
                volume_index[vid] = {
                    "id": vol.id,
                    "name": vol.name,
                    "bounds": {
                        "xmin": vol.xmin, "ymin": vol.ymin, "zmin": vol.zmin,
                        "xmax": vol.xmax, "ymax": vol.ymax, "zmax": vol.zmax,
                    },
                    "site": vol.site,
                }

        soft_adjacent: list[dict[str, Any]] = []
        craft_warnings: list[dict[str, Any]] = []
        for i, a in enumerate(wps):
            for b in wps[i + 1 :]:
                if not (a.start and b.start and a.finish and b.finish):
                    continue
                if not self._ranges_overlap(a.start, a.finish, b.start, b.finish):
                    continue
                if a.volume_id and b.volume_id and a.volume_id == b.volume_id:
                    vol_info = volume_index.get(a.volume_id, {"id": a.volume_id})
                    flagged.append(
                        {
                            "wp_a": a.id,
                            "wp_b": b.id,
                            "volume_id": a.volume_id,
                            "volume": vol_info,
                            "severity": "hard",
                            "overlap_start": max(a.start, b.start).isoformat(),
                            "overlap_finish": min(a.finish, b.finish).isoformat(),
                            "disciplines": [a.discipline.value, b.discipline.value],
                        }
                    )
                elif (
                    a.volume_id
                    and b.volume_id
                    and self.graph
                    and a.volume_id in self.graph.volumes
                    and b.volume_id in self.graph.volumes
                ):
                    va = self.graph.volumes[a.volume_id]
                    vb = self.graph.volumes[b.volume_id]
                    if volumes_adjacent(va, vb, gap_m=2.0):
                        soft_adjacent.append(
                            {
                                "wp_a": a.id,
                                "wp_b": b.id,
                                "volume_a": a.volume_id,
                                "volume_b": b.volume_id,
                                "severity": "soft_adjacent",
                                "overlap_start": max(a.start, b.start).isoformat(),
                                "overlap_finish": min(a.finish, b.finish).isoformat(),
                                "disciplines": [a.discipline.value, b.discipline.value],
                            }
                        )
        # craft density: tags per m³ per day
        if self.graph:
            for wp in wps:
                if not wp.volume_id or wp.volume_id not in self.graph.volumes:
                    continue
                vol = self.graph.volumes[wp.volume_id]
                vol_m3 = max(
                    (vol.xmax - vol.xmin) * (vol.ymax - vol.ymin) * (vol.zmax - vol.zmin),
                    1e-6,
                )
                days = max((wp.finish - wp.start).days, 1)  # type: ignore[operator]
                density = len(wp.tags) / vol_m3 / days
                if density > 0.05:  # heuristic threshold
                    craft_warnings.append(
                        {
                            "wp_id": wp.id,
                            "severity": "craft_density",
                            "tags_per_m3_per_day": round(density, 6),
                            "threshold": 0.05,
                        }
                    )
        return {
            "hard_count": len(flagged),
            "soft_count": len(soft_adjacent),
            "same_volume_count": len(flagged),
            "adjacent_count": len(soft_adjacent),
            "flagged_count": len(flagged),
            "flagged": flagged,
            "soft_adjacent": soft_adjacent,
            "craft_warnings": craft_warnings,
            "volumes_involved": sorted({f["volume_id"] for f in flagged}),
            "message": (
                f"Co-activity — {len(flagged)} hard, {len(soft_adjacent)} soft-adjacent, "
                f"{len(craft_warnings)} craft-density warnings"
            ),
        }

    def look_ahead(
        self,
        weeks: int = 3,
        from_date: Optional[Union[str, date]] = None,
        disciplines: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """List activities / WPs in [from_date, from_date + weeks], optional discipline filter.

        disciplines: e.g. ["PIP","INS","ELE","TEL"] — filter activities & WPs.
        """
        start = _parse_date(from_date) if from_date else self.schedule_date
        end = start + timedelta(weeks=weeks)
        disc_filter = {d.upper() for d in disciplines} if disciplines else None

        window_activities: list[dict[str, Any]] = []
        for act in self.activities.values():
            if self._ranges_overlap(act.start, act.finish, start, end):
                dval = act.discipline.value if act.discipline else None
                if disc_filter and (dval is None or dval not in disc_filter):
                    continue
                window_activities.append(act.model_dump(mode="json"))

        window_wps: list[dict[str, Any]] = []
        if self.graph:
            for wp in self.graph.work_packages.values():
                if wp.start and wp.finish and self._ranges_overlap(wp.start, wp.finish, start, end):
                    if disc_filter and wp.discipline.value not in disc_filter:
                        continue
                    row = wp.model_dump(mode="json")
                    meta = wp.metadata or {}
                    weight = float(meta.get("weight_kg") or 0.0)
                    # CS piping norm 0.35 h/kg (public rule-of-thumb; flagged)
                    crew_hours = round(weight * 0.35, 2)
                    row["iwp_id"] = wp.id if wp.wp_type.value == "IWP" else meta.get("parent_cwp")
                    row["weight_kg"] = weight
                    row["crew_hours"] = crew_hours
                    row["norm_source"] = "0.35 h/kg CS piping (public planning norm)"
                    window_wps.append(row)

        by_discipline: dict[str, int] = {}
        for a in window_activities:
            d = a.get("discipline") or "UNK"
            by_discipline[d] = by_discipline.get(d, 0) + 1

        return {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "weeks": weeks,
            "disciplines_filter": sorted(disc_filter) if disc_filter else None,
            "activities": window_activities,
            "work_packages": window_wps,
            "activity_count": len(window_activities),
            "wp_count": len(window_wps),
            "by_discipline": by_discipline,
        }

    def export_look_ahead_csv(
        self,
        path: Union[str, Path],
        weeks: int = 3,
        from_date: Optional[Union[str, date]] = None,
        disciplines: Optional[list[str]] = None,
    ) -> Path:
        """Write look-ahead activities to CSV."""
        result = self.look_ahead(weeks=weeks, from_date=from_date, disciplines=disciplines)
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "id", "name", "wp_id", "discipline", "start", "finish", "man_hours", "status",
        ]
        with out.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for act in result["activities"]:
                writer.writerow(act)
        return out

    def export_co_activity_report(
        self,
        path: Union[str, Path],
        disciplines: Optional[list[str]] = None,
    ) -> Path:
        """Write co-activity report JSON (with volume details)."""
        report = self.co_activity_check(disciplines=disciplines)
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return out

    def attach_to_work_packages(self) -> int:
        """Copy activity dates onto matching WPs. Returns updated count."""
        if not self.graph:
            return 0
        updated = 0
        for act in self.activities.values():
            if act.wp_id and act.wp_id in self.graph.work_packages:
                wp = self.graph.work_packages[act.wp_id]
                wp.start = act.start
                wp.finish = act.finish
                updated += 1
        return updated
