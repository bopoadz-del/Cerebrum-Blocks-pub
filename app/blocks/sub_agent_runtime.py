"""Sub-Agent Runtime — spawn contract with environment scrubbing, ported
from <private-repo> ``agent/swarm/spawner.py``.

The multiprocessing/LLM layers are not ported. The store block ports the
isolation CONTRACT: a sub-agent inherits only the scrub allowlist
(PATH, PYTHONPATH, AIRGAP, TEST_MODE, DATA_DIR, OLLAMA_URL, OLLAMA_MODEL),
the process cap is enforced (spawn refused past the cap), and the payload
must validate before any spawn is admitted. In-process bookkeeping.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "sub_agent_runtime", "status": status, "result": result, "error": error, "detail": detail}


# The donor's exact allowlist.
SCRUB_ALLOWED = (
    "PATH",
    "PYTHONPATH",
    "AIRGAP",
    "TEST_MODE",
    "DATA_DIR",
    "OLLAMA_URL",
    "OLLAMA_MODEL",
)

_MAX_PROCESSES = 8


def scrubbed_env(source: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env: Dict[str, str] = {}
    src = source or {}
    for key in SCRUB_ALLOWED:
        val = src.get(key)
        if val is not None:
            env[key] = val
    return env


class SubAgentRuntimeBlock(UniversalBlock):
    """Sub-agent spawn contract: scrubbed env, process cap, payload
    validation — ported from <private-repo> spawner.py."""

    name = "sub_agent_runtime"
    version = "1.0.0"
    description = (
        "Sub-agent spawn contract ported from <private-repo> agent/swarm/spawner.py: "
        "the child inherits only the scrub allowlist (PATH/PYTHONPATH/AIRGAP/"
        "TEST_MODE/DATA_DIR/OLLAMA_*), the process cap is enforced, and the "
        "payload validates before any spawn is admitted. In-process bookkeeping."
    )
    layer = 3
    tags = ["agent", "spawn", "isolation", "<private-repo>"]
    requires = []

    default_config = {"max_processes": _MAX_PROCESSES, "scrub_allowlist": list(SCRUB_ALLOWED)}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "spawn", "env": {"SECRET": "x", "DATA_DIR": "/d"}, "payload": {"task": "x"}}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._running: Dict[str, Dict[str, Any]] = {}

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "spawn")).lower()
        try:
            if action == "scrub":
                return _envelope("ok", {"env": scrubbed_env(payload.get("env"))})
            if action == "spawn":
                return self._spawn(payload)
            if action == "reap":
                aid = str(payload.get("agent_id", ""))
                rec = self._running.pop(aid, None)
                return _envelope("ok", {"agent_id": aid, "existed": rec is not None})
            if action == "running":
                return _envelope("ok", {"running": list(self._running.values()), "count": len(self._running)})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["scrub", "spawn", "reap", "running"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    def _spawn(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if len(self._running) >= int(payload.get("max_processes", self.default_config["max_processes"])):
            return _envelope("refused", error="process cap reached", detail={"cap": self.default_config["max_processes"]})
        task = payload.get("payload")
        if not isinstance(task, dict) or not task.get("task"):
            return _envelope("error", error="payload.task is required before any spawn is admitted")
        env = scrubbed_env(payload.get("env"))
        agent_id = f"sub-{len(self._running) + 1}"
        self._running[agent_id] = {"agent_id": agent_id, "task": str(task.get("task")), "env": env, "spawned_at": __import__("time").time()}
        return _envelope("ok", {"agent_id": agent_id, "env": env})
