"""project_reasoner fails loud when provider credentials are absent.

The manifest acceptance oracle ``missing_credential`` is backed by this:
_call_llm raises RuntimeError naming the missing env key instead of
fabricating an answer or silently downgrading.
"""

from __future__ import annotations

import asyncio

import pytest

from app.blocks.project_reasoner import ProjectReasonerBlock


def test_call_llm_refuses_when_env_key_unset(monkeypatch):
    from app.core.llm_config import _llm_config

    cfg = _llm_config()
    monkeypatch.delenv(cfg["env_key"], raising=False)
    block = ProjectReasonerBlock()
    with pytest.raises(RuntimeError, match="not configured"):
        asyncio.run(block._call_llm("what is the critical path?"))
