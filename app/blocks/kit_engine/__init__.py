"""Shared reasoning-layer evaluator: eight invariant kinds, five hooks.

A kit is a DECLARATION — `manifest.yaml` (the vocabulary) plus `invariants.yaml`
(the records). Nothing in the evaluator knows what a runway or a slab is.

Sixteen hand-written gates is sixteen chances to order the rules wrong, and two
such bugs were written and found by hand in the first kit built that way. One
evaluator reading one declaration cannot have a different ordering bug per
domain.

Fail closed: a kit that does not parse is DISABLED, and a disabled kit refuses
every statement. Each kit also has a kill switch, CEREBRUM_KIT_<NAME>=off.
"""
from app.blocks.kit_engine.engine import (  # noqa: F401
    DEFAULT_BUDGET,
    DisabledKit,
    Kit,
    KitLoadError,
    KitRegistry,
    kill_switch_off,
    load_kit,
)
from app.blocks.kit_engine.figure import Figure, Finding, Outcome  # noqa: F401
from app.blocks.kit_engine.invariants import (  # noqa: F401
    H0_PRE_RETRIEVAL,
    H1_RANKING,
    H2_TOOL_TIME,
    H3_ANSWER_TIME,
    H4_EXPORT_TIME,
    KINDS,
    Invariant,
    check_arithmetic,
)
from app.blocks.kit_engine.interview import (  # noqa: F401
    DesignBasis,
    Interview,
    InterviewError,
    Question,
    load_design_basis,
    load_interview,
    parse_interview,
)
from app.blocks.kit_engine.manifest import Manifest, ManifestError  # noqa: F401
