"""Block Store container kit API — discovery and install."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.container_kit_store import (
    ContainerKitError,
    get_kit,
    install_kit,
    list_installed,
    list_kits,
    uninstall_kit,
)
from app.dependencies import require_api_key

router = APIRouter(tags=["store"])


class InstallRequest(BaseModel):
    force: bool = Field(default=False, description="Overwrite existing files")
    target_root: Optional[str] = Field(
        default=None,
        description="Install target root (defaults to Cerebrum project root)",
    )


@router.get("/containers")
def store_list_containers():
    """List publishable container kits (discovery — no auth required)."""
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
                "tier": k.get("tier", "standard"),
                "note": k.get("note"),
                "status": k.get("status"),
                "coming_soon": k.get("coming_soon", False),
                "bundle_ready": k.get("bundle_ready", False),
                "skeleton_ready": k.get("skeleton_ready", False),
                "skeleton_installable": k.get("skeleton_installable", False),
                "installable": k.get("installable", False),
                "source": k.get("source"),
                "blocks": k.get("blocks", []),
                "skeleton_artifacts": k.get("skeleton_artifacts", []),
            }
            for k in kits
        ],
        "total": len(kits),
    }


@router.get("/containers/installed")
def store_list_installed(auth: dict = Depends(require_api_key)):
    """List kits installed on this instance."""
    return list_installed()


@router.get("/containers/{kit_id}")
def store_get_container(kit_id: str):
    """Full kit manifest for install preview."""
    try:
        kit = get_kit(kit_id)
    except ContainerKitError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return kit


@router.post("/containers/{kit_id}/install")
def store_install_container(
    kit_id: str,
    body: InstallRequest = InstallRequest(),
    auth: dict = Depends(require_api_key),
):
    """Install a container kit from the store bundle into this instance."""
    target = Path(body.target_root).resolve() if body.target_root else None
    try:
        result = install_kit(kit_id, target_root=target, force=body.force)
    except ContainerKitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/containers/{kit_id}/uninstall")
def store_uninstall_container(
    kit_id: str,
    auth: dict = Depends(require_api_key),
):
    """Remove files from the last install of this kit."""
    try:
        return uninstall_kit(kit_id)
    except ContainerKitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# /store/* aliases (Block Store UI + public discovery docs)
@router.get("/store/containers")
def store_list_containers_store_prefix():
    return store_list_containers()


@router.get("/store/containers/installed")
def store_list_installed_store_prefix(auth: dict = Depends(require_api_key)):
    return store_list_installed()


@router.get("/store/containers/{kit_id}")
def store_get_container_store_prefix(kit_id: str):
    return store_get_container(kit_id)


@router.post("/store/containers/{kit_id}/install")
def store_install_container_store_prefix(
    kit_id: str,
    body: InstallRequest = InstallRequest(),
    auth: dict = Depends(require_api_key),
):
    return store_install_container(kit_id, body, auth)


# Versioned aliases (match /v1/blocks pattern)
@router.get("/v1/store/containers")
def store_list_containers_v1():
    return store_list_containers()


@router.get("/v1/store/containers/{kit_id}")
def store_get_container_v1(kit_id: str):
    return store_get_container(kit_id)


@router.post("/v1/store/containers/{kit_id}/install")
def store_install_container_v1(
    kit_id: str,
    body: InstallRequest = InstallRequest(),
    auth: dict = Depends(require_api_key),
):
    return store_install_container(kit_id, body, auth)
