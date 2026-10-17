from fastapi import APIRouter

from app.blocks import BLOCK_REGISTRY

router = APIRouter()


@router.get("/")
async def root():
    """Platform root — new UI will be served here."""
    return {
        "name": "Cerebrum Blocks",
        "version": "2.0.0",
        "tagline": "Build AI Like Lego",
        "blocks": len(BLOCK_REGISTRY),
        "status": "ui_rebuilding",
        "message": "New UI is being deployed. Check back shortly.",
    }


@router.get("/api")
def api_info():
    """API info."""
    return {
        "name": "Cerebrum Blocks",
        "version": "2.0.0",
        "tagline": "Build AI Like Lego",
        "blocks": len(BLOCK_REGISTRY),
        "endpoints": {
            "blocks": "/v1/blocks",
            "registry": "/v1/registry/blocks/{block_id}",
            "execute": "/v1/execute",
            "chain": "/v1/chain",
            "chat": "/v1/chat",
            "health": "/v1/health",
        },
    }
