# Ported (real) from <private-repo> src/<private-repo>/cascade.py (donor HEAD on disk).
# Intra-package imports are rewritten to relative imports; the code is
# otherwise carried verbatim. DEXPI ingestion is NOT duplicated here: the
# Store's dexpi_ingest block (ported from ingest_dexpi.py) covers ingestion,
# and this package carries the downstream digital thread (graph, routing,
# tables, clash, schedule 4D, generators, PCF, maturity, cascade, exporters).
# The agent/API layers (agent_tools, cli, server, mcp_server) are not ported.
"""Change → dirty artefacts cascade for the digital thread."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .graph import TopologyGraph
from .models import (
    ArtefactDescriptor,
    ArtefactKind,
    ChangeEvent,
    DirtySet,
    JobPipeline,
    JobStage,
    StageStatus,
)

# Downstream artefacts dirtied when a tag or line changes
TAG_DIRTY_KINDS = [
    ArtefactKind.ROUTES,  # geometry first — dependents must re-read graph.routes
    ArtefactKind.SUPPORTS,
    ArtefactKind.ISOMETRIC,
    ArtefactKind.QUANTITIES,
    ArtefactKind.TEST_PACK,
    ArtefactKind.WORK_PACKAGE,
    ArtefactKind.PCF,
    ArtefactKind.SYSTEM,
    ArtefactKind.CLASH,
    ArtefactKind.GA,
]

LINE_DIRTY_KINDS = [
    ArtefactKind.ROUTES,  # mark routes dirty before PCF/ISO/qty dependents
    ArtefactKind.SUPPORTS,
    ArtefactKind.ISOMETRIC,
    ArtefactKind.QUANTITIES,
    ArtefactKind.PCF,
    ArtefactKind.CLASH,
    ArtefactKind.GA,
    ArtefactKind.TEST_PACK,
    ArtefactKind.WORK_PACKAGE,
]

STAGE_CASCADE: dict[JobStage, list[JobStage]] = {
    JobStage.UPLOAD: [JobStage.TOPOLOGY, JobStage.LAYOUT, JobStage.PIPING, JobStage.OUTPUTS],
    JobStage.TOPOLOGY: [JobStage.LAYOUT, JobStage.PIPING, JobStage.OUTPUTS],
    JobStage.LAYOUT: [JobStage.PIPING, JobStage.OUTPUTS],
    JobStage.PIPING: [JobStage.OUTPUTS],
    JobStage.OUTPUTS: [],
}


class CascadeEngine:
    """Tracks changes and computes dirty artefact sets; marks pipeline stages."""

    def __init__(self, graph: TopologyGraph, job: Optional[JobPipeline] = None) -> None:
        self.graph = graph
        self.job = job
        self.events: list[ChangeEvent] = []
        self.artefacts: dict[str, ArtefactDescriptor] = {}
        self.last_dirty: Optional[DirtySet] = None

    def register_artefact(self, art: ArtefactDescriptor) -> None:
        self.artefacts[art.id] = art

    def record_change(
        self,
        entity_type: str,
        entity_id: str,
        action: str = "revise",
        details: Optional[dict[str, Any]] = None,
    ) -> ChangeEvent:
        event = ChangeEvent(
            id=f"CHG-{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(timezone.utc),
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            details=details or {},
        )
        self.events.append(event)
        dirty = self.compute_dirty(event)
        self.last_dirty = dirty
        self._apply_dirty(dirty)
        return event

    def compute_dirty(self, event: ChangeEvent) -> DirtySet:
        kinds: list[ArtefactKind]
        if event.entity_type in ("tag", "equipment", "instrument", "nozzle"):
            kinds = list(TAG_DIRTY_KINDS)
        elif event.entity_type in ("pipeline", "line"):
            kinds = list(LINE_DIRTY_KINDS)
        else:
            kinds = list(TAG_DIRTY_KINDS)

        artefact_ids: list[str] = []
        for art in self.artefacts.values():
            related = False
            if event.entity_id in art.related_tags or event.entity_id in art.related_lines:
                related = True
            if art.kind in kinds and (
                related
                or not art.related_tags
                and not art.related_lines  # global artefacts
            ):
                artefact_ids.append(art.id)

        # WPs that contain the changed tag / line components
        affected_wps: list[str] = []
        for wp in self.graph.work_packages.values():
            if event.entity_id in wp.tags:
                affected_wps.append(wp.id)
            else:
                # line change: if any WP tag belongs to that line
                pipe = self.graph.pipelines.get(event.entity_id)
                if pipe:
                    line_tags = set(pipe.component_tags)
                    if pipe.from_tag:
                        line_tags.add(pipe.from_tag)
                    if pipe.to_tag:
                        line_tags.add(pipe.to_tag)
                    if line_tags.intersection(wp.tags):
                        affected_wps.append(wp.id)

        # Also dirty WPs by volume if tag has volume
        tag = self.graph.tags.get(event.entity_id)
        if tag and tag.volume_id:
            for wp in self.graph.work_packages.values():
                if wp.volume_id == tag.volume_id and wp.id not in affected_wps:
                    affected_wps.append(wp.id)

        affected_stages = [
            JobStage.PIPING,
            JobStage.OUTPUTS,
        ]
        if event.entity_type in ("tag", "equipment", "pipeline", "line"):
            affected_stages = [JobStage.TOPOLOGY, JobStage.PIPING, JobStage.OUTPUTS]

        return DirtySet(
            change_id=event.id,
            artefact_kinds=kinds,
            artefact_ids=artefact_ids,
            affected_wp_ids=affected_wps,
            affected_stages=affected_stages,
        )

    def _apply_dirty(self, dirty: DirtySet) -> None:
        # Shared geometry invalidated before any dependent regenerates.
        if ArtefactKind.ROUTES in dirty.artefact_kinds:
            self.graph.routes.clear()
        for aid in dirty.artefact_ids:
            if aid in self.artefacts:
                self.artefacts[aid].status = "dirty"
        for wid in dirty.affected_wp_ids:
            wp = self.graph.work_packages.get(wid)
            if wp:
                wp.status = "dirty"
        if self.job:
            for stage in dirty.affected_stages:
                st = self.job.stage_state(stage)
                if st.status == StageStatus.DONE:
                    st.status = StageStatus.DIRTY
                    st.updated_at = datetime.now(timezone.utc)
                    st.message = f"Dirtied by {dirty.change_id}"
            # Cascade further downstream
            for stage in list(dirty.affected_stages):
                for down in STAGE_CASCADE.get(stage, []):
                    st = self.job.stage_state(down)
                    if st.status == StageStatus.DONE:
                        st.status = StageStatus.DIRTY
                        st.updated_at = datetime.now(timezone.utc)

    def dirty_summary(self) -> dict[str, Any]:
        if not self.last_dirty:
            return {"dirty": False}
        d = self.last_dirty
        return {
            "dirty": True,
            "change_id": d.change_id,
            "artefact_kinds": [k.value for k in d.artefact_kinds],
            "artefact_ids": list(d.artefact_ids),
            "affected_wp_ids": list(d.affected_wp_ids),
            "affected_stages": [s.value for s in d.affected_stages],
        }
