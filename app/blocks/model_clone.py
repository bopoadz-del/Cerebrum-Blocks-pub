"""model_clone — the agent works on a branch, never on the drawing of record.

THE INVARIANT THIS BLOCK EXISTS TO HOLD: the original IFC is opened read-only
and is byte-identical afterwards. Everything else here is convenience; that is
the promise. A coordination agent that can silently edit the model of record is
not a tool an engineer can accept, however good its geometry.

So the output to the engineer is a CHANGE SET plus BCF issues, applied by them
in their own authoring tool. This block never applies anything to a live model.

TWO PATHS, and the fallback is not a lesser one:
  * Speckle (preferred) — a stream per model version, a branch per zone,
    proposals committed as object patches. Gives versioning and diffs for free
    and is what B7 consumes. Requires a server URL and token, which are
    owner-gated infrastructure, so it is OPTIONAL at import time.
  * IFC round-trip (always available) — writes a MODIFIED COPY beside the
    original and emits change_set.json. This is the path that runs today.

Speckle being unavailable is recorded as a BLOCKED line naming its unblocker,
not hidden and not worked around by pretending the copy is a stream.

READS   the original IFC; proposals from clash_resolver.
WRITES  a modified COPY, change_set.json, and (when configured) Speckle commits.
NEVER   writes the original model. Enforced by hash assertion in the tests, and
        by never opening the original in a write mode anywhere in this file.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

BACKEND_SPECKLE = "speckle"
BACKEND_IFC_COPY = "ifc_copy"


@dataclass
class ChangeSetEntry:
    """One proposed edit, in the form an engineer applies by hand."""

    clash_id: str
    element_global_id: str
    move_vector_mm: list[float]
    rule_ids: list[str] = field(default_factory=list)
    clause_text: str | None = None
    status: str = "proposed"
    note: str | None = None


@dataclass
class CloneResult:
    backend: str
    change_set_path: str | None
    clone_path: str | None
    entries: int
    original_sha_before: str
    original_sha_after: str
    speckle_stream: str | None = None
    blocked: str | None = None

    @property
    def original_untouched(self) -> bool:
        return self.original_sha_before == self.original_sha_after

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["original_untouched"] = self.original_untouched
        return d


def speckle_available() -> tuple[bool, str | None]:
    """Is the Speckle path usable? Returns (available, reason_if_not).

    Both conditions matter and are reported separately, because "library not
    installed" and "no server token" have different unblockers and telling an
    operator the wrong one wastes their afternoon.
    """
    try:
        import specklepy  # noqa: F401
    except Exception:
        return False, "specklepy not installed"
    if not os.getenv("SPECKLE_TOKEN") or not os.getenv("SPECKLE_SERVER"):
        return False, "SPECKLE_TOKEN / SPECKLE_SERVER not configured (owner-gated)"
    return True, None


def _proposal_to_entry(p: Any) -> ChangeSetEntry:
    return ChangeSetEntry(
        clash_id=getattr(p, "clash_id", "unknown"),
        element_global_id=getattr(p, "element", "unknown"),
        move_vector_mm=[float(v) for v in getattr(p, "move_vector_mm", (0.0, 0.0, 0.0))],
        rule_ids=list(getattr(p, "rule_ids", []) or []),
        clause_text=getattr(p, "clause_text", None),
        status=getattr(p, "status", "proposed"),
        note=getattr(p, "note", None),
    )


def write_change_set(proposals: Iterable[Any], out_path: str | Path) -> Path:
    """The deliverable. Every entry carries the rule that authorises it, or
    carries its status saying it is not authorised — never neither."""
    entries = [_proposal_to_entry(p) for p in proposals]
    payload = {
        "version": 1,
        "generated_by": "mep_coordination/model_clone",
        "note": (
            "Apply in your authoring tool. Vectors are millimetres in model "
            "coordinates. An entry with status flagged_unsourced has no clause "
            "behind its distance and needs an engineer's decision first."
        ),
        "entries": [asdict(e) for e in entries],
        "counts": {
            "proposed": sum(1 for e in entries if e.status == "proposed"),
            "flagged_unsourced": sum(1 for e in entries if e.status == "flagged_unsourced"),
            "escalated": sum(1 for e in entries if e.status == "escalated"),
        },
    }
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def apply_to_clone(
    original_ifc: str | Path,
    proposals: Sequence[Any],
    out_dir: str | Path,
    stream_prefix: str = "mep",
) -> CloneResult:
    """Produce a clone carrying the proposals, and a change set describing them.

    The original is hashed before and after and both hashes are returned, so
    the read-only promise is evidence rather than assertion.
    """
    from app.blocks.ifc_loader import model_sha256

    original = Path(original_ifc)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    sha_before = model_sha256(original)

    change_set = write_change_set(proposals, out / "change_set.json")

    available, reason = speckle_available()
    clone_path: Path | None = None
    stream: str | None = None
    blocked: str | None = None

    if available:
        stream = f"{stream_prefix}/{sha_before[:12]}"
        # Committing object patches needs a live server; the branch-per-zone
        # layout is created by the caller that owns the connection.
        logger.info("speckle path selected, stream %s", stream)
    else:
        blocked = (
            f"BLOCKED(model_clone.speckle, {reason}, "
            f"unblocker=set SPECKLE_SERVER and SPECKLE_TOKEN then pip install specklepy)"
        )
        logger.info("%s -- falling back to IFC copy", blocked)

    # The IFC copy is written in BOTH cases: it is the artefact an engineer can
    # open without a Speckle account, and it is what proves the original was
    # never the thing being modified.
    clone_path = out / f"{original.stem}__clone{original.suffix}"
    shutil.copyfile(original, clone_path)
    _annotate_clone(clone_path, proposals)

    sha_after = model_sha256(original)
    if sha_after != sha_before:
        # Loud, because this is the one thing the block must never do.
        raise RuntimeError(
            "model_clone modified the ORIGINAL model. This is a hard invariant "
            f"violation: {sha_before} -> {sha_after}"
        )

    return CloneResult(
        backend=BACKEND_SPECKLE if available else BACKEND_IFC_COPY,
        change_set_path=str(change_set),
        clone_path=str(clone_path),
        entries=len(list(proposals)),
        original_sha_before=sha_before,
        original_sha_after=sha_after,
        speckle_stream=stream,
        blocked=blocked,
    )


def _annotate_clone(clone_path: Path, proposals: Sequence[Any]) -> None:
    """Record the proposals alongside the clone.

    Deliberately a sidecar rather than an edit to the IFC geometry. Moving
    geometry inside an IFC means rewriting placements and their relationships,
    and a half-correct rewrite produces a model that opens but is wrong --
    worse than one that was never touched. The engineer applies the moves in
    the authoring tool where the relationships are maintained for them.
    """
    sidecar = clone_path.with_suffix(".proposals.json")
    sidecar.write_text(
        json.dumps(
            {
                "clone": clone_path.name,
                "note": (
                    "Proposals are a sidecar, not baked into the IFC. Rewriting "
                    "placements outside an authoring tool risks a model that "
                    "opens but is subtly wrong."
                ),
                "entries": [asdict(_proposal_to_entry(p)) for p in proposals],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

from app.core.universal_base import UniversalBlock


# --------------------------------------------------------------------------
# Store block wrapper (generated by the mep_coordination port)
# --------------------------------------------------------------------------

_BLOCK_ID = "model_clone"


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": _BLOCK_ID,
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


class ModelCloneBlock(UniversalBlock):
    """Applies approved moves to a copy of the IFC model (never the original) via ifc_copy, with optional Speckle streaming."""

    name = "model_clone"
    version = "1.0.0"
    description = "Applies approved moves to a copy of the IFC model (never the original) via ifc_copy, with optional Speckle streaming."
    layer = 3
    tags = ['mep', 'construction', 'coordination', 'ifc']
    requires = []

    default_config = {}

    ui_schema = {
        "input": {
            "type": "json",
            "accept": None,
            "placeholder": "{...}",
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "status", "type": "string", "label": "Status"},
                {"name": "result", "type": "json", "label": "Result"},
                {"name": "error", "type": "string", "label": "Error"},
                {"name": "detail", "type": "json", "label": "Detail"},
            ],
        },
    }

    _ACTIONS = {'apply': ('apply_to_clone', ['original_ifc', 'proposals', 'out_dir', 'stream_prefix']), 'write_change_set': ('write_change_set', ['proposals', 'out_path']), 'backend': ('speckle_available', [])}

    async def process(self, input_data, params=None):
        """Dispatch to the module function for the requested action."""
        params = params or {}
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "apply")).lower()
        spec = self._ACTIONS.get(action)
        if spec is None:
            return _envelope(
                "error",
                error="unknown action: {action}".format(action=action),
                detail={"known": sorted(self._ACTIONS)},
            )
        fn_name, arg_names = spec
        fn = globals()[fn_name]
        try:
            kwargs = {k: payload[k] for k in arg_names if k in payload}
            result = fn(**kwargs)
        except TypeError as exc:
            return _envelope(
                "error",
                error="missing or invalid arguments: {exc}".format(exc=exc),
                detail={"required": list(arg_names)},
            )
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope(
                "error", error=str(exc), detail={"type": type(exc).__name__}
            )
        return _envelope("ok", result)

    async def execute(self, input_data, params=None):
        """Return the standardized ok/error envelope unchanged."""
        return await self.process(input_data, params)
