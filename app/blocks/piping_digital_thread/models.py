# Ported (real) from <private-repo> src/<private-repo>/models.py (donor HEAD on disk).
# Intra-package imports are rewritten to relative imports; the code is
# otherwise carried verbatim. DEXPI ingestion is NOT duplicated here: the
# Store's dexpi_ingest block (ported from ingest_dexpi.py) covers ingestion,
# and this package carries the downstream digital thread (graph, routing,
# tables, clash, schedule 4D, generators, PCF, maturity, cascade, exporters).
# The agent/API layers (agent_tools, cli, server, mcp_server) are not ported.
"""Pydantic models for the <private-repo> digital thread."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Maturity & pipeline enums
# ---------------------------------------------------------------------------

class MaturityLevel(str, Enum):
    """Design maturity gates (FEED → IFC), matching UI spirit."""

    FEED = "FEED"
    L1 = "L1"
    L2 = "L2"
    L3_60 = "L3_60"  # ~60 % model review
    L4_90 = "L4_90"  # ~90 % model review
    IFC = "IFC"  # Issued For Construction


# Ordered for comparisons
MATURITY_ORDER: list[MaturityLevel] = [
    MaturityLevel.FEED,
    MaturityLevel.L1,
    MaturityLevel.L2,
    MaturityLevel.L3_60,
    MaturityLevel.L4_90,
    MaturityLevel.IFC,
]


class JobStage(str, Enum):
    """Pid-to-3d pipeline stages."""

    UPLOAD = "upload"
    TOPOLOGY = "topology"
    LAYOUT = "layout"
    PIPING = "piping"
    OUTPUTS = "outputs"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    DIRTY = "dirty"
    FAILED = "failed"


class Discipline(str, Enum):
    PIP = "PIP"
    EQP = "EQP"
    INS = "INS"
    ELE = "ELE"
    TEL = "TEL"
    STR = "STR"
    CIV = "CIV"


class WPType(str, Enum):
    CWA = "CWA"
    CWP = "CWP"  # Construction Work Package
    IWP = "IWP"  # Installation Work Package


class ArtefactKind(str, Enum):
    ISOMETRIC = "isometric"
    QUANTITIES = "quantities"
    TEST_PACK = "test_pack"
    WORK_PACKAGE = "work_package"
    PCF = "pcf"
    DLB = "dlb"
    GA = "ga"
    CSV = "csv"
    SYSTEM = "system"
    SUPPORTS = "supports"
    ROUTES = "routes"
    CLASH = "clash"
    IFC = "ifc"
    DXF = "dxf"


# ---------------------------------------------------------------------------
# Identity / taxonomy helpers
# ---------------------------------------------------------------------------

class IdentityTaxonomy(BaseModel):
    """Identity & taxonomy attributes shown in equipment side panels."""

    std_name: Optional[str] = None
    primary_code: Optional[str] = None
    ccs_base: Optional[str] = None
    ccs_type_code: Optional[str] = None
    sequence: Optional[str] = None


class EngineeringAttributes(BaseModel):
    component_class: Optional[str] = None  # e.g. EQ
    equipment_description: Optional[str] = None
    service: Optional[str] = None
    station_m: Optional[float] = None  # position along route (m), optional
    extra: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core engineering entities
# ---------------------------------------------------------------------------

class Tag(BaseModel):
    """Atomic digital-thread unit — equipment, line, instrument, etc."""

    id: str
    name: str
    discipline: Discipline = Discipline.PIP
    sheet_id: Optional[str] = None
    identity: IdentityTaxonomy = Field(default_factory=IdentityTaxonomy)
    engineering: EngineeringAttributes = Field(default_factory=EngineeringAttributes)
    volume_id: Optional[str] = None
    asset_3d_ref: Optional[str] = None  # path / CAD id (e.g. GLB or TS001)
    geometry_bounds: Optional[dict[str, float]] = None  # xmin,ymin,xmax,ymax
    status: str = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)


class Pipeline(BaseModel):
    """Piping line / pipeline segment."""

    id: str
    line_number: str
    from_tag: Optional[str] = None
    to_tag: Optional[str] = None
    nominal_bore: Optional[str] = None
    service: Optional[str] = None
    material: Optional[str] = None
    sheet_id: Optional[str] = None
    component_tags: list[str] = Field(default_factory=list)  # elbows, flanges, …
    status: str = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)


class FromTo(BaseModel):
    """Directed connectivity edge between two tags / nozzles."""

    id: str
    from_id: str
    to_id: str
    via_line: Optional[str] = None
    connection_type: str = "pipe"  # pipe | nozzle | instrument | opc_cross_page
    matched: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class BatteryLimit(BaseModel):
    """Battery-limit / interface tag."""

    id: str
    tag_id: str
    description: Optional[str] = None
    side: Optional[str] = None  # upstream | downstream | external


class Sheet(BaseModel):
    """P&ID sheet metadata (multi-sheet projects)."""

    id: str
    name: str
    index: int = 1
    total: int = 1
    source_xml: Optional[str] = None
    source_svg: Optional[str] = None
    notes: list[str] = Field(default_factory=list)
    legend: dict[str, str] = Field(default_factory=dict)
    layers: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Nozzle(BaseModel):
    id: str
    tag: str
    equipment_id: str
    size: Optional[str] = None
    rating: Optional[str] = None
    facing: Optional[str] = None
    orientation: Optional[str] = None
    # Optional plant coordinates (mm or m — units noted in metadata/PCF header)
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    # Drawing/sheet coordinates from Position/Location — NEVER copied into x/y/z
    drawing_xy: Optional[tuple[float, float]] = None


class Equipment(BaseModel):
    id: str
    tag: str
    description: Optional[str] = None
    identity: IdentityTaxonomy = Field(default_factory=IdentityTaxonomy)
    engineering: EngineeringAttributes = Field(default_factory=EngineeringAttributes)
    nozzles: list[str] = Field(default_factory=list)
    asset_3d_ref: Optional[str] = None
    volume_id: Optional[str] = None
    sheet_id: Optional[str] = None


class Instrument(BaseModel):
    id: str
    tag: str
    instrument_type: Optional[str] = None  # PT, FT, LT, …
    measured_variable: Optional[str] = None
    connected_to: Optional[str] = None
    sheet_id: Optional[str] = None
    discipline: Discipline = Discipline.INS


class DesignVolume(BaseModel):
    """Spatial bounding box used for AWP / work-package generation."""

    id: str
    name: str
    xmin: float = 0.0
    ymin: float = 0.0
    zmin: float = 0.0
    xmax: float = 10.0
    ymax: float = 10.0
    zmax: float = 10.0
    color: Optional[str] = None
    site: Optional[str] = None
    plot_plan_ref: Optional[str] = None


class System(BaseModel):
    id: str
    name: str
    boundary_tags: list[str] = Field(default_factory=list)
    subsystems: list[str] = Field(default_factory=list)
    service: Optional[str] = None


class Subsystem(BaseModel):
    id: str
    name: str
    system_id: str
    tags: list[str] = Field(default_factory=list)


class TestPack(BaseModel):
    id: str
    name: str
    system_id: str
    tags: list[str] = Field(default_factory=list)
    status: str = "draft"
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkPackage(BaseModel):
    """CWP / IWP with discipline, volume, tags, and schedule window."""

    id: str
    name: str
    wp_type: WPType = WPType.CWP
    discipline: Discipline = Discipline.PIP
    volume_id: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    start: Optional[date] = None
    finish: Optional[date] = None
    status: str = "planned"  # planned | in_progress | complete
    quantity_measure: Optional[str] = None  # e.g. "12,721 m"
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Change / cascade
# ---------------------------------------------------------------------------

class ChangeEvent(BaseModel):
    id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    entity_type: str  # tag | pipeline | nozzle | …
    entity_id: str
    action: str  # revise | add | delete
    details: dict[str, Any] = Field(default_factory=dict)


class DirtySet(BaseModel):
    """Artefacts dirtied by a change that need re-generation."""

    change_id: str
    artefact_kinds: list[ArtefactKind] = Field(default_factory=list)
    artefact_ids: list[str] = Field(default_factory=list)
    affected_wp_ids: list[str] = Field(default_factory=list)
    affected_stages: list[JobStage] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Job pipeline
# ---------------------------------------------------------------------------

class StageState(BaseModel):
    stage: JobStage
    status: StageStatus = StageStatus.PENDING
    message: Optional[str] = None
    updated_at: Optional[datetime] = None


class JobPipeline(BaseModel):
    """Five-stage Pid-to-3d job lifecycle."""

    job_id: str
    name: str = "untitled"
    target_maturity: MaturityLevel = MaturityLevel.L4_90
    current_maturity: MaturityLevel = MaturityLevel.FEED
    stages: list[StageState] = Field(
        default_factory=lambda: [StageState(stage=s) for s in JobStage]
    )
    sheet_count: int = 0
    site_type: str = "onshore"
    metadata: dict[str, Any] = Field(default_factory=dict)

    def stage_state(self, stage: JobStage) -> StageState:
        for s in self.stages:
            if s.stage == stage:
                return s
        raise KeyError(stage)


# ---------------------------------------------------------------------------
# Artefact descriptors (stubs return these)
# ---------------------------------------------------------------------------

class ArtefactDescriptor(BaseModel):
    id: str
    kind: ArtefactKind
    status: str = "stub"  # stub | ready | dirty | failed
    path: Optional[str] = None
    related_tags: list[str] = Field(default_factory=list)
    related_lines: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    message: Optional[str] = None


# ---------------------------------------------------------------------------
# Schedule activity (for 4D)
# ---------------------------------------------------------------------------

class ScheduleActivity(BaseModel):
    id: str
    name: str
    wp_id: Optional[str] = None
    discipline: Optional[Discipline] = None
    start: date
    finish: date
    man_hours: Optional[float] = None
    status: str = "planned"
