"""Minimal mock backend for testing the workflow builder frontend.
Serves /blocks, /chain, /store/containers, and /v1/workflows for local dev."""

import json
import os
from pathlib import Path

# Dev key (cb_dev_key) is only registered when ENV is local/test/dev.
os.environ.setdefault("ENV", "local")

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

app = FastAPI(title="Cerebrum Mock Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

REGISTRY_DIR = Path(__file__).resolve().parent.parent / "block_registry"


def _load_registry_blocks():
    blocks = []
    if not REGISTRY_DIR.exists():
        return blocks
    for subdir in sorted(REGISTRY_DIR.iterdir()):
        if not subdir.is_dir():
            continue
        manifest = subdir / "block.json"
        if not manifest.exists():
            continue
        try:
            with open(manifest, "r", encoding="utf-8") as f:
                m = json.load(f)
            blocks.append({
                "name": m["id"],
                "version": m.get("version", "1.0"),
                "description": m.get("description", ""),
                "layer": m.get("layer", 3),
                "tags": m.get("tags", []),
                "requires": m.get("requires", []),
                "ui_schema": m.get("ui_schema", {}),
                "source": "registry",
            })
        except Exception:
            continue
    return blocks


MOCK_BLOCKS = _load_registry_blocks()


class ChainStep(BaseModel):
    block: str
    params: Dict[str, Any] = {}
    label: Optional[str] = None
    input_mapping: Optional[Dict[str, str]] = None


class ChainRequest(BaseModel):
    steps: List[ChainStep]
    initial_input: Any = None
    fail_fast: bool = True
    continue_on_error: bool = False


@app.get("/health")
def health():
    return {"status": "healthy", "blocks_loaded": len(MOCK_BLOCKS)}


@app.get("/blocks")
def list_blocks():
    return {"blocks": MOCK_BLOCKS, "total": len(MOCK_BLOCKS), "categories": {}}


@app.post("/chain")
def chain_execute(req: ChainRequest):
    results = []
    current_output = req.initial_input or {}
    for i, step in enumerate(req.steps):
        # Mock execution: echo params back as output
        current_output = {
            "step": i,
            "block": step.block,
            "params": step.params,
            "result": f"Mock output from {step.block}",
            "success": True,
            "status": "success",
        }
        results.append(current_output)

    return {
        "success": True,
        "status": "success",
        "steps_executed": len(req.steps),
        "final_output": current_output,
        "results": results,
        "validation_passed": True,
    }


@app.get("/store/containers")
def mock_store_containers():
    from app.core.container_kit_store import list_kits

    kits = list_kits()
    return {
        "containers": [
            {
                "id": k["id"],
                "name": k.get("name"),
                "version": k.get("version"),
                "description": k.get("description"),
                "tags": k.get("tags", []),
                "author": k.get("author"),
                "price_cents": k.get("price_cents", 0),
                "status": k.get("status"),
                "coming_soon": k.get("coming_soon", False),
                "bundle_ready": k.get("bundle_ready", False),
                "source": k.get("source"),
                "blocks": k.get("blocks", []),
            }
            for k in kits
        ],
        "total": len(kits),
    }


@app.get("/store/containers/installed")
def mock_store_installed():
    from app.core.container_kit_store import list_installed

    return list_installed()


@app.get("/store/containers/{kit_id}")
def mock_store_container_detail(kit_id: str):
    from app.core.container_kit_store import ContainerKitError, get_kit

    try:
        return get_kit(kit_id)
    except ContainerKitError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class MockInstallRequest(BaseModel):
    force: bool = False
    target_root: Optional[str] = None


@app.post("/store/containers/{kit_id}/install")
def mock_store_install(kit_id: str, body: MockInstallRequest = MockInstallRequest()):
    from pathlib import Path

    from app.core.container_kit_store import ContainerKitError, install_kit

    target = Path(body.target_root).resolve() if body.target_root else None
    try:
        return install_kit(kit_id, target_root=target, force=body.force)
    except ContainerKitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Reactive workflow triggers — same router as production (app/main.py).
from app.routers.workflows import router as workflows_router

app.include_router(workflows_router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
