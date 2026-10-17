"""Console Floor pack — router.

Serves the console at `/` and the pack's API surface:
  GET  /v1/capabilities    capability discovery (never hardcoded names)
  POST /v1/pack/formulas   execute the product's formulas capability
  GET  /v1/store/packs     pack catalog listing (Store catalog integration)

The formulas endpoint requires the same API-key guard as /v1/execute; the
console lets the operator paste a token rather than embedding one.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.blocks import BLOCK_REGISTRY, get_block
from app.dependencies import require_api_key

logger = logging.getLogger(__name__)

_PACK_DIR = (
    Path(__file__).resolve().parents[2] / "block_store" / "packs" / "console_floor"
)
_CONSOLE_HTML = _PACK_DIR / "console" / "index.html"
_PACKS_ROOT = _PACK_DIR.parent

router = APIRouter()


@router.get("/", include_in_schema=False)
async def console_index(request: Request) -> HTMLResponse:
    """The ONE UI, served at the root. No build step: the pack ships only
    the console."""
    html = _CONSOLE_HTML.read_text(encoding="utf-8")
    return HTMLResponse(html)


@router.get("/v1/capabilities")
async def capabilities() -> JSONResponse:
    """Discover capabilities from the live registry — works for any product
    that adopts the pack. The formulas capability is always first (it is the
    pack's own surface); block capabilities follow in registry order."""
    caps: list = [
        {
            "id": "formulas",
            "name": "Formulas",
            "kind": "pack",
            "description": "Evaluate the product's formulas via app.formulas",
        }
    ]
    for name in BLOCK_REGISTRY:
        caps.append({"id": name, "name": name, "kind": "block"})
    return JSONResponse({"capabilities": caps, "count": len(caps)})


@router.post("/v1/pack/formulas")
async def run_formula(payload: Dict[str, Any], auth: dict = Depends(require_api_key)) -> JSONResponse:
    """Execute a product formula. The answer carries its authority label:
    grounding verdict + source layer."""
    from app.formulas import evaluate

    formula_id = str(payload.get("formula_id", ""))
    variables = payload.get("variables") or {}
    if not isinstance(variables, dict):
        return JSONResponse(
            status_code=422,
            content={"status": "error", "error": "variables must be an object"},
        )
    try:
        result = await evaluate(formula_id, variables)
    except Exception as exc:  # noqa: BLE001 — envelope must not crash consumers
        logger.exception("formulas execution failed")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": str(exc)},
        )
    return JSONResponse(result)


@router.get("/v1/store/packs")
async def list_packs() -> JSONResponse:
    """Store catalog listing for the pack artifact type."""
    packs = []
    if _PACKS_ROOT.is_dir():
        for manifest_path in sorted(_PACKS_ROOT.glob("*/manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if manifest.get("type") == "pack":
                packs.append(
                    {
                        "id": manifest.get("id"),
                        "name": manifest.get("name"),
                        "version": manifest.get("version"),
                        "description": manifest.get("description"),
                    }
                )
    return JSONResponse({"packs": packs, "count": len(packs)})
