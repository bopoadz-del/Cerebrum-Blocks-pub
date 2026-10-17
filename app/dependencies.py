"""Shared dependencies and block instance management for FastAPI app."""

import asyncio
import inspect
import logging
import os
import sys
from typing import Any, Dict, Optional

from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.blocks import BLOCK_REGISTRY, get_block_capabilities
from app.blocks.memory import MemoryBlock, MemoryNamespaceProxy
from app.core.block_proxy import CapabilityProxy
from app.core.auth import auth as auth_manager
from app.core.domain_kit_loader import _KIT_BLOCK_SPECS

logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# HAL initialization
try:
    from app.core.hal import HALBlock
    _hal = HALBlock()

    def get_hal_block():
        # Exposed via the same accessor pattern memory/monitoring/auth use,
        # so _resolve_dep("hal") finds it for blocks declaring requires=["hal"]
        # (config.py is the main one).
        return _hal

    HAL_AVAILABLE = True
except Exception as e:
    logger.warning("HALBlock not available during startup: %s", e)
    _hal = None
    get_hal_block = None  # type: ignore[assignment]
    HAL_AVAILABLE = False

# Shared block instances
block_instances: Dict[str, Any] = {}

# Block names that come from third-party domain kits (vs. core platform blocks).
_KIT_BLOCK_NAMES = {
    name for specs in _KIT_BLOCK_SPECS.values() for name, _, _ in specs
}

_PRIVATE_NAMESPACES = {
    "auth": "__auth",
    "monitoring": "__monitoring",
    "secrets": "__secrets",
}


def _memory_namespace_for_block(name: str) -> str:
    """Return the private memory namespace a block instance should use."""
    if name in _PRIVATE_NAMESPACES:
        return _PRIVATE_NAMESPACES[name]
    if name in _KIT_BLOCK_NAMES:
        return f"block:{name}"
    return f"system:{name}"



def _create_block_instance(block_class, config: Optional[Dict] = None, allow_platform: bool = True):
    """Create block instance with proper arguments.

    ``allow_platform`` controls whether ``set_platform`` is called. Core blocks
    receive the platform registry; third-party blocks do not, to prevent them
    from obtaining unmediated access to other blocks or the memory cache.
    """
    # Choke-point tier gate: any restricted primitive instantiated inside an
    # authenticated request must pass the tier check, even on dispatch paths
    # (swarm/workflow/notify/...) that never called enforce_block_access.
    from app.core.security import enforce_restricted_resolution
    enforce_restricted_resolution(getattr(block_class, "name", "") or "")

    sig = inspect.signature(block_class.__init__)
    params = list(sig.parameters.keys())

    if "hal_block" in params and "config" in params:
        instance = block_class(hal_block=_hal, config=config or {})
    else:
        instance = block_class()

    if allow_platform and hasattr(instance, "set_platform"):
        try:
            instance.set_platform(BLOCK_REGISTRY, block_instances, _create_block_instance, get_memory_block)
        except Exception:
            pass

    return instance


async def _legacy_initialize_once(instance: Any) -> None:
    """Call _legacy_initialize exactly once per instance."""
    if getattr(instance, "_legacy_initialized", False):
        return
    init = getattr(instance, "_legacy_initialize", None)
    if init is None:
        instance._legacy_initialized = True  # nothing to do
        return
    try:
        await init()
    except Exception:
        logger.exception(
            "Legacy initialization failed for %s",
            getattr(instance, "name", type(instance).__name__),
        )
    finally:
        instance._legacy_initialized = True


def _schedule_legacy_initialize(instance: Any) -> None:
    """Schedule _legacy_initialize on the running event loop if available."""
    if getattr(instance, "_legacy_initialized", False):
        return
    if getattr(instance, "_legacy_initialize_task", None) is not None:
        return
    if not hasattr(instance, "_legacy_initialize"):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    instance._legacy_initialize_task = loop.create_task(_legacy_initialize_once(instance))


def _resolve_dep(dep_name: str):
    """Look up a dep instance via four sources, in order:

    1. block_instances (already wired)
    2. BLOCK_REGISTRY (lazy-instantiate via get_block_instance)
    3. Legacy accessor `get_<name>_block()` (memory/monitoring/auth live here)
    4. Globals — caches like `_memory_block` set by the legacy accessors

    Returns the instance, or None if no source has it. None is fine — most
    dependent blocks check `if self.X_block:` before using the dep, and the
    audit caught the few that didn't.
    """
    if dep_name in block_instances:
        return block_instances[dep_name]
    if dep_name in BLOCK_REGISTRY:
        try:
            return get_block_instance(dep_name)
        except Exception:
            logger.warning("dep_resolver: %s in BLOCK_REGISTRY but failed to instantiate", dep_name)
    accessor = globals().get(f"get_{dep_name}_block")
    if callable(accessor):
        try:
            return accessor()
        except Exception:
            logger.warning("dep_resolver: legacy accessor get_%s_block failed", dep_name)
    cached = globals().get(f"_{dep_name}_block")
    if cached is not None:
        return cached
    return None


def _wire_block_dependencies(instance, block_class, name: str = None, caps=None):
    """Wire requires=[] dependencies into a platform block instance.

    The audit found 31 blocks with requires=["config"|"database"|"memory"|...]
    where the dep name isn't in BLOCK_REGISTRY. Previous version silently
    skipped — the block then crashed on first use of self.X_block. Now we
    resolve via four sources (registry → lazy instance → legacy accessor →
    cached global) and only skip + log when none has it.

    If ``caps`` is provided, dependencies not listed in ``permissions.blocks``
    are skipped. This prevents a third-party block from obtaining references
    to blocks it did not declare.
    """
    requires = getattr(block_class, "requires", []) or []
    for dep_name in requires:
        if caps is not None and not caps.allows_block_access(dep_name):
            logger.warning(
                "block %s is not permitted to access '%s' (not in permissions.blocks); skipping",
                name or "?", dep_name,
            )
            continue
        dep_instance = _resolve_dep(dep_name)
        if dep_instance is None:
            logger.warning(
                "block %s requires '%s' but no provider found "
                "(not in BLOCK_REGISTRY, no get_%s_block accessor) — "
                "block will run without it; calls that touch self.%s_block may fail.",
                name or "?", dep_name, dep_name, dep_name,
            )
            continue
        # Scope memory dependencies to a per-block namespace so blocks cannot
        # read each other's keys or the global cache.
        if dep_name == "memory" and isinstance(dep_instance, MemoryBlock):
            dep_instance = MemoryNamespaceProxy(
                dep_instance, _memory_namespace_for_block(name or "unknown")
            )
        if hasattr(instance, "wire"):
            instance.wire(dep_name, dep_instance)
        elif hasattr(instance, "inject"):
            instance.inject(dep_name, dep_instance)
        # Always set the legacy attribute as well (e.g. self.memory_block)
        attr_name = f"{dep_name}_block"
        if hasattr(instance, attr_name) or dep_name in requires:
            setattr(instance, attr_name, dep_instance)


def get_block_instance(block_name: str, config: Optional[Dict] = None) -> Any:
    # Choke-point tier gate — runs on every call, including cache hits, so a
    # dispatch path cannot reach a restricted block by resolving a cached one.
    from app.core.security import enforce_restricted_resolution
    enforce_restricted_resolution(block_name)
    if block_name not in block_instances:
        block_class = BLOCK_REGISTRY[block_name]
        caps = get_block_capabilities(block_name)
        from app.blocks import _is_core_block
        is_core = _is_core_block(block_name)
        # Core blocks are trusted and receive the platform registry.
        # Third-party blocks do not, to prevent unmediated access.
        instance = _create_block_instance(block_class, config, allow_platform=is_core)
        # Non-core blocks get a capability proxy so unsafe caps cannot run
        # inside the main process.
        if not is_core:
            instance = CapabilityProxy(instance, caps)
        block_instances[block_name] = instance
        _wire_block_dependencies(block_instances[block_name], block_class, block_name, caps)
        _schedule_legacy_initialize(block_instances[block_name])
    return block_instances[block_name]


# Memory block
def get_memory_block():
    """Return the shared memory cache instance (registry-first)."""
    return get_block_instance("memory")


# Monitoring block
def get_monitoring_block():
    """Return the shared monitoring block instance."""
    return get_block_instance("monitoring")


# Auth block
def get_auth_block():
    """Return the shared auth block instance."""
    master_key = os.getenv("CEREBRUM_MASTER_KEY")
    if "auth" in block_instances:
        instance = block_instances["auth"]
        if master_key and instance.config.get("master_key") != master_key:
            instance.config["master_key"] = master_key
            instance.master_key = master_key
        return instance
    config = {"master_key": master_key} if master_key else {}
    return get_block_instance("auth", config)


# Availability flags — the modern blocks are registered lazily, so presence in
# BLOCK_REGISTRY is enough to know they are available.
MEMORY_AVAILABLE = "memory" in BLOCK_REGISTRY
MONITORING_AVAILABLE = "monitoring" in BLOCK_REGISTRY
AUTH_AVAILABLE = "auth" in BLOCK_REGISTRY


security = HTTPBearer(auto_error=False)


async def require_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """Require valid API key for protected endpoints"""
    auth = auth_manager.validate_key(credentials)
    from app.core.security import set_current_auth
    set_current_auth(auth)
    return auth


async def init_blocks():
    """Lazy-only initialisation — pre-warm runs in a thread pool.

    Earlier we pre-warmed core blocks here (chat/pdf/ocr/construction/
    smart_orchestrator/skills) which pulls in sklearn/sympy/ezdxf etc.
    Even as a background asyncio task, those synchronous imports BLOCK
    THE EVENT LOOP. Render's health checker then times out hitting
    /health, marks the worker unhealthy, and kills it — visible in the
    service event log as `server_failed` with `dial tcp: connect: ...`.

    Now: pre-warm runs in a thread executor so the event loop stays
    responsive throughout. /health responds instantly during the pre-warm
    window. First /v1/execute on a not-yet-warm block pays a small lazy-
    import cost (~50–500ms depending on the block).

    Override via env:
        BLOCKS_PREWARM=none → skip pre-warm entirely (pure lazy)
        BLOCKS_PREWARM=all  → pre-warm every registered block (benchmark)
        BLOCKS_PREWARM=core → default; pre-warm SPA happy-path blocks
    """
    prewarm_mode = os.getenv("BLOCKS_PREWARM", "core").strip().lower()
    if prewarm_mode == "none":
        return

    if prewarm_mode == "all":
        targets = list(BLOCK_REGISTRY.keys())
    else:
        targets = [
            "chat", "pdf", "ocr", "skills",
        ]

    def _warm_target(name: str) -> None:
        if name in block_instances:
            return
        try:
            block_class = BLOCK_REGISTRY[name]
            block_instances[name] = _create_block_instance(block_class)
        except Exception as e:
            logger.warning("Failed to initialise block %s: %s", name, e)

    loop = asyncio.get_running_loop()
    for name in targets:
        # to_thread() runs the synchronous import in the default executor —
        # event loop continues serving /health and other fast endpoints.
        await asyncio.to_thread(_warm_target, name)

    # Wire deps for whatever we did manage to instantiate (cheap, no imports)
    for name, instance in list(block_instances.items()):
        block_class = BLOCK_REGISTRY.get(name)
        if block_class:
            _wire_block_dependencies(instance, block_class, name)

    # The accessors below schedule async _legacy_initialize which REQUIRES a
    # running event loop — must be invoked from the loop, not via to_thread.
    if get_memory_block:
        try: get_memory_block()
        except Exception: logger.exception("get_memory_block init failed")
    if get_monitoring_block:
        try: get_monitoring_block()
        except Exception: logger.exception("get_monitoring_block init failed")
    if get_auth_block:
        try: get_auth_block()
        except Exception: logger.exception("get_auth_block init failed")

    try:
        if "smart_orchestrator" in block_instances and "skills" in block_instances:
            orch = block_instances["smart_orchestrator"]
            skills = block_instances["skills"]
            if hasattr(orch, "wire_skills"):
                orch.wire_skills(skills)
    except Exception as e:
        logger.warning("Failed to wire skills into smart_orchestrator: %s", e)
