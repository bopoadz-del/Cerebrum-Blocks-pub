"""The in-process sandbox must not leave a memory cap on its host.

It exec()s in the host process, so RLIMIT_AS set there lands on the host --
the API server of whatever platform cloned this block. It used to set the
soft AND hard limit and restore neither: one sandboxed call capped the whole
process for life. Seen as a MemoryError cascade that took a full CI run down
right after tests/blocks/test_sandbox_isolated_requires_runner.py.
"""

from __future__ import annotations

import asyncio

import pytest

resource = pytest.importorskip("resource", reason="RLIMIT_AS is Unix-only")


def _run(code: str):
    from app.blocks.sandbox import SandboxBlock, SandboxPolicy

    block = SandboxBlock()
    # Far above any real process: RLIMIT_AS counts VIRTUAL address space, and
    # a test process with ML libraries loaded is already past 512 MB. These
    # tests are about the limit being put back, not about it biting.
    policy = SandboxPolicy(max_memory_mb=64 * 1024)
    return asyncio.run(block._execute_python(code, policy, {}))


def test_the_hosts_limit_is_exactly_what_it_was():
    before = resource.getrlimit(resource.RLIMIT_AS)

    out = _run("result = 1 + 1")

    assert out["success"] is True and out["result"] == 2
    assert resource.getrlimit(resource.RLIMIT_AS) == before


def test_the_limit_is_restored_when_the_code_raises():
    before = resource.getrlimit(resource.RLIMIT_AS)

    out = _run("raise ValueError('boom')")

    assert out["success"] is False
    assert resource.getrlimit(resource.RLIMIT_AS) == before


def test_the_hard_limit_is_never_lowered():
    """A non-root process cannot raise a hard limit back. Ever."""
    hard_before = resource.getrlimit(resource.RLIMIT_AS)[1]

    _run("result = 0")

    assert resource.getrlimit(resource.RLIMIT_AS)[1] == hard_before
