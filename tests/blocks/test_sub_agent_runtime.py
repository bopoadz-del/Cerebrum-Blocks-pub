"""Sub-agent runtime tests — ported spawn contract from <private-repo>."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.sub_agent_runtime import SubAgentRuntimeBlock, scrubbed_env


def _run(coro):
    return asyncio.run(coro)


def test_env_scrub_keeps_only_allowlist():
    env = scrubbed_env({"DATA_DIR": "/d", "SECRET_KEY": "x", "AWS_TOKEN": "y", "PATH": "/bin", "OTHER": "z"})
    assert set(env) == {"DATA_DIR", "PATH"}
    assert "SECRET_KEY" not in env and "AWS_TOKEN" not in env


def test_spawn_requires_valid_payload():
    b = SubAgentRuntimeBlock()
    r = _run(b.process({"action": "spawn", "env": {}, "payload": {}}))
    assert r["status"] == "error"
    assert "payload.task" in r["error"]


def test_spawn_and_reap():
    b = SubAgentRuntimeBlock()
    r = _run(b.process({"action": "spawn", "env": {"DATA_DIR": "/d", "SECRET": "x"}, "payload": {"task": "probe"}}))
    assert r["status"] == "ok"
    assert "SECRET" not in r["result"]["env"]
    aid = r["result"]["agent_id"]
    reap = _run(b.process({"action": "reap", "agent_id": aid}))
    assert reap["result"]["existed"] is True


def test_process_cap_refused():
    b = SubAgentRuntimeBlock()
    for i in range(8):
        _run(b.process({"action": "spawn", "payload": {"task": f"t{i}"}}))
    r = _run(b.process({"action": "spawn", "payload": {"task": "overflow"}}))
    assert r["status"] == "refused"
    assert "cap" in r["error"]
