"""Exact-id registry lookup — Factory STEP 0 REUSE / inventory."""

from fastapi import APIRouter, Depends

from app.block_registry import registry_reuse_lookup
from app.dependencies import require_api_key

router = APIRouter(tags=["registry"])


@router.get("/registry/blocks/{block_id}")
def registry_block_present(block_id: str, auth: dict = Depends(require_api_key)):
    """Exact-id ``REUSE present?`` query against ``block_registry/``.

    Auth-gated the same way ``/v1/blocks`` is: the registry is a recon
    surface. Factory calls this with the exact block id from a brief;
    the answer is whether that id exists on disk, plus the manifest
    (including L2.2 ``reads`` / ``writes`` / ``never`` / ``acceptance``)
    when it does.

    Always 200. ``present`` / ``reuse`` are the inventory bits — a miss
    is a negative lookup, not a 404, so a compiler can treat the body
    as a registry query result.
    """
    return registry_reuse_lookup(block_id)


@router.get("/v1/registry/blocks/{block_id}")
def registry_block_present_v1(block_id: str, auth: dict = Depends(require_api_key)):
    """Versioned alias of ``GET /registry/blocks/{block_id}``."""
    return registry_block_present(block_id, auth)


@router.get("/v1/registry/reuse/{block_id}")
def registry_reuse_present_v1(block_id: str, auth: dict = Depends(require_api_key)):
    """Factory STEP 0 name for the exact-id REUSE lookup."""
    return registry_block_present(block_id, auth)
