"""Tests for the shared, domain-agnostic formula_executor_v2 block."""

from __future__ import annotations

import pytest

from app.core.sandbox import run_sandboxed, SandboxResult
from app.prompts.codegen_system import build_codegen_prompt
from app.blocks.formula_executor_v2 import FormulaExecutorV2Block


# ---------------------------------------------------------------------------
# Prompt policy tests
# ---------------------------------------------------------------------------


def test_prompt_allows_numpy():
    prompt = build_codegen_prompt("sum an array", {})
    assert "numpy" in prompt


def test_prompt_allows_sympy():
    prompt = build_codegen_prompt("solve symbolically", {})
    assert "sympy" in prompt


def test_prompt_allows_pint():
    prompt = build_codegen_prompt("convert units", {})
    assert "pint" in prompt


def test_prompt_blocks_scipy():
    prompt = build_codegen_prompt("interpolate", {})
    assert "scipy" in prompt.lower()
    assert "not allowed" in prompt.lower() or "not allowed" in prompt


def test_prompt_is_domain_agnostic():
    prompt = build_codegen_prompt("calculate", {})
    assert "construction-project intelligence" not in prompt.lower()
    assert "domain intelligence platform" in prompt.lower()


def test_prompt_states_auditable_calculations_only():
    prompt = build_codegen_prompt("calculate", {})
    assert "deterministic, auditable calculations" in prompt
    assert "network access" in prompt
    assert "file access" in prompt


# ---------------------------------------------------------------------------
# Sandbox import tests
# ---------------------------------------------------------------------------


def test_sandbox_accepts_numpy():
    out = run_sandboxed("import numpy as np\nresult = int(np.array([1, 2, 3]).sum())")
    assert out.success is True
    assert out.result == 6


def test_sandbox_accepts_sympy():
    out = run_sandboxed(
        'import sympy as sp\nx = sp.Symbol("x")\nresult = str(sp.expand((x + 1) ** 2))'
    )
    assert out.success is True
    assert "x**2" in out.result


def test_sandbox_accepts_pint():
    out = run_sandboxed(
        "import pint\n"
        "ureg = pint.UnitRegistry()\n"
        "q = 3 * ureg.meter + 200 * ureg.centimeter\n"
        "result = str(q.to(ureg.meter))"
    )
    assert out.success is True
    assert "5" in out.result
    assert "meter" in out.result


def test_sandbox_rejects_scipy():
    out = run_sandboxed("import scipy\nresult = 1")
    assert out.success is False
    assert "blocked" in out.error.lower() or "not allowed" in out.error.lower()


# ---------------------------------------------------------------------------
# FormulaExecutorV2Block process tests with mocked LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
def _mock_llm(code: str):
    async def _inner(prompt: str) -> str:
        return _fence(code)
    return _inner


@pytest.mark.asyncio
async def test_block_runs_numpy_code():
    block = FormulaExecutorV2Block()
    block._call_llm = _mock_llm("import numpy as np\nresult = int(np.array([1, 2, 3]).sum())")
    out = await block.process({"task": "sum array"})
    assert out["status"] == "success"
    assert out["result"] == 6


@pytest.mark.asyncio
async def test_block_runs_sympy_code():
    block = FormulaExecutorV2Block()
    block._call_llm = _mock_llm('import sympy as sp\nx = sp.Symbol("x")\nresult = str(sp.expand((x + 1) ** 2))')
    out = await block.process({"task": "expand binomial"})
    assert out["status"] == "success"
    assert "x**2" in out["result"]


@pytest.mark.asyncio
async def test_block_runs_pint_code():
    block = FormulaExecutorV2Block()
    block._call_llm = _mock_llm(
        "import pint\n"
        "ureg = pint.UnitRegistry()\n"
        "q = 3 * ureg.meter + 200 * ureg.centimeter\n"
        "result = str(q.to(ureg.meter))"
    )
    out = await block.process({"task": "convert units"})
    assert out["status"] == "success"
    assert "meter" in out["result"]


@pytest.mark.asyncio
async def test_block_retries_then_fails_on_scipy():
    block = FormulaExecutorV2Block()
    block._call_llm = _mock_llm("import scipy\nresult = 1")
    out = await block.process({"task": "use scipy"})
    assert out["status"] == "error"
    assert out["attempts"] >= 1


def _fence(code: str) -> str:
    return f"```python\n{code}\n```"


# ==========================================================================
# HARVESTED FROM The_Fork: tests/test_formula_executor_v2.py
#
# The Store's own file above is mock-shaped prompt/sandbox coverage. These
# tests drive FormulaExecutorV2Block.process end to end: generate -> run ->
# retry-on-traceback -> cache -> re-run cached code. They are what makes a
# control-delete of process() go RED.
#
# LAYOUT ADAPTATIONS (The_Fork -> Cerebrum-Blocks), assertions unchanged:
#   * The_Fork's app/core/session_store.py (InMemorySessionStore) has no
#     counterpart here, only the ProjectSession schema such a store holds.
#     Sessions are built with ProjectSession.new(); the store round-trip test
#     round-trips through model_dump()/model_validate() instead of
#     save()/get(), which is the same serialise-and-reload the store performs.
#
# NOT HARVESTED (and why):
#   * test_legacy_v1_name_no_longer_registered -- asserts "formula_executor"
#     is absent from BLOCK_REGISTRY. That is The_Fork's audit decision; this
#     repo ships app/blocks/formula_executor.py deliberately and registers it
#     in the construction kit, so the assertion is wrong here, not weak.
#   * test_v2_is_registered -- registration here is gated on an active domain
#     kit (CEREBRUM_DOMAIN_KITS), not unconditional as in The_Fork; the Store
#     already covers it in tests/core/test_kit_block_validation.py.
# ==========================================================================

from app.schemas.project_session import ProjectSession


class _MockLLMBlock(FormulaExecutorV2Block):
    """Test double — returns canned code instead of calling DeepSeek.

    `scripted` is a list of code strings yielded one per LLM call, so a test
    can script a first failing attempt followed by a passing retry.
    """

    def __init__(self, scripted, **kw):
        super().__init__(**kw)
        self._scripted = list(scripted)
        self.llm_calls = 0

    async def _call_llm(self, prompt: str) -> str:
        self.llm_calls += 1
        return self._scripted.pop(0)


def test_prompt_states_the_result_contract():
    p = build_codegen_prompt("compute slab volume", {"length_m": 10})
    # The generated code must assign to a variable called `result`.
    assert "result" in p
    assert "```python" in p or "code block" in p.lower()


def test_prompt_lists_available_variables():
    p = build_codegen_prompt("area", {"length_m": 10, "width_m": 8})
    assert "length_m" in p and "width_m" in p


def test_prompt_advertises_the_pm_library():
    p = build_codegen_prompt("critical path", {})
    # Generated code may import the tested CPM library instead of re-deriving it.
    assert "app.lib.pm_computations" in p
    assert "compute_cpm" in p


def test_prompt_allows_numpy_sympy_pint():
    p = build_codegen_prompt("compute volume with units", {})
    assert "numpy" in p
    assert "sympy" in p
    assert "pint" in p


def test_prompt_does_not_allow_scipy():
    p = build_codegen_prompt("compute volume", {})
    # SciPy must remain blocked; it may appear only in the explicit denial.
    assert "scipy" in p.lower()
    # The allowed-import line must not list scipy.
    allowed_line = next(
        line for line in p.splitlines() if "MAY import ONLY" in line
    )
    assert "scipy" not in allowed_line


def test_prompt_includes_retry_context_when_given():
    p = build_codegen_prompt(
        "area", {"length_m": 10},
        prior_code="result = length_m *",
        prior_error="SyntaxError: invalid syntax",
    )
    assert "SyntaxError" in p
    assert "result = length_m *" in p


def test_prompt_omits_retry_section_on_first_attempt():
    p = build_codegen_prompt("area", {"length_m": 10})
    assert "previous attempt" not in p.lower()


@pytest.mark.asyncio
async def test_v2_generates_and_runs_code():
    block = _MockLLMBlock(["result = length_m * width_m"])
    out = await block.process({
        "task": "rectangle area",
        "variables": {"length_m": 10, "width_m": 8},
    })
    assert out["status"] == "success"
    assert out["result"] == 80
    assert out["generated_code"] == "result = length_m * width_m"
    assert block.llm_calls == 1


@pytest.mark.asyncio
async def test_v2_strips_markdown_fences_from_llm_output():
    # LLMs wrap code in ```python fences — the block must unwrap them.
    block = _MockLLMBlock(["```python\nresult = length_m * 2\n```"])
    out = await block.process({"task": "double", "variables": {"length_m": 5}})
    assert out["status"] == "success"
    assert out["result"] == 10
    assert "```" not in out["generated_code"]


@pytest.mark.asyncio
async def test_v2_retries_after_a_runtime_failure():
    # First attempt references an undefined name; retry fixes it.
    block = _MockLLMBlock([
        "result = lenght_m * width_m",       # typo -> NameError
        "result = length_m * width_m",       # corrected
    ])
    out = await block.process({
        "task": "rectangle area",
        "variables": {"length_m": 10, "width_m": 8},
    })
    assert out["status"] == "success"
    assert out["result"] == 80
    assert out["attempts"] == 2
    assert block.llm_calls == 2


@pytest.mark.asyncio
async def test_v2_gives_up_after_max_retries():
    # Every attempt fails -> 1 initial + 2 retries = 3 LLM calls, then error.
    block = _MockLLMBlock([
        "result = undefined_a",
        "result = undefined_b",
        "result = undefined_c",
    ])
    out = await block.process({"task": "x", "variables": {}})
    assert out["status"] == "error"
    assert out["attempts"] == 3
    assert block.llm_calls == 3
    assert out["traceback"] is not None


@pytest.mark.asyncio
async def test_v2_passes_traceback_into_the_retry_prompt():
    captured = []

    class _Spy(_MockLLMBlock):
        async def _call_llm(self, prompt):
            captured.append(prompt)
            return await super()._call_llm(prompt)

    block = _Spy(["result = bad_name", "result = 1"])
    await block.process({"task": "x", "variables": {}})
    # Second prompt must carry the prior code + error for self-correction.
    assert "bad_name" in captured[1]
    assert "previous attempt" in captured[1].lower()


@pytest.mark.asyncio
async def test_v2_runs_generated_numpy_code():
    block = _MockLLMBlock([
        "import numpy as np\nresult = int(np.array([1, 2, 3]).sum())"
    ])
    out = await block.process({
        "task": "sum an array with numpy",
        "variables": {},
    })
    assert out["status"] == "success"
    assert out["result"] == 6
    assert "numpy" in out["generated_code"]


@pytest.mark.asyncio
async def test_v2_runs_generated_sympy_code():
    block = _MockLLMBlock([
        "import sympy as sp\nx = sp.Symbol('x')\nresult = str(sp.expand((x + 1) ** 2))"
    ])
    out = await block.process({
        "task": "expand a symbolic expression",
        "variables": {},
    })
    assert out["status"] == "success"
    assert "x**2" in out["result"]


def test_sandbox_rejects_scipy_import():
    out = run_sandboxed("import scipy\nresult = 1")
    assert out.success is False
    assert "scipy" in (out.error or "").lower()


@pytest.mark.asyncio
async def test_v2_caches_successful_code_on_the_session():
    session = ProjectSession.new("s1")
    block = _MockLLMBlock(["result = length_m * 2"])
    await block.process({
        "task": "double the length", "variables": {"length_m": 5},
        "session": session,
    })
    # the generated code is cached under the session's code_cache
    assert any("result = length_m * 2" in v
               for v in session.code_cache.values())


@pytest.mark.asyncio
async def test_v2_reuses_cached_code_without_calling_the_llm():
    session = ProjectSession.new("s1")
    block = _MockLLMBlock(["result = length_m * 2"])
    first = await block.process({
        "task": "double the length", "variables": {"length_m": 5},
        "session": session,
    })
    assert first["result"] == 10 and block.llm_calls == 1

    # Same task + same variable KEYS -> cache hit, no second LLM call.
    second = await block.process({
        "task": "double the length", "variables": {"length_m": 9},
        "session": session,
    })
    assert second["status"] == "success"
    assert second["result"] == 18           # re-runs cached code with new value
    assert second.get("cache_hit") is True
    assert block.llm_calls == 1             # LLM NOT called again


@pytest.mark.asyncio
async def test_v2_cache_survives_a_full_store_round_trip():
    # The cache contract: process() mutates the session by reference, and the
    # CALLER must persist it. Serialising and reloading the session (what a
    # session store does on save/get) only carries the cache if the dump is
    # taken AFTER process() writes it — mirroring project_ask's
    # reasoner -> ... -> save(session) flow.
    # Turn 1: cache miss — process() writes code_cache.
    session = ProjectSession.new("round-trip")
    block1 = _MockLLMBlock(["result = length_m * 3"])
    first = await block1.process({
        "task": "triple the length", "variables": {"length_m": 4},
        "session": session,
    })
    assert first["status"] == "success"
    assert first.get("cache_hit") is False
    assert block1.llm_calls == 1
    persisted = session.model_dump()               # caller persists the turn

    # Turn 2: a fresh session object is loaded from the store; the cached
    # code must be there, so process() hits the cache and skips the LLM.
    reloaded = ProjectSession.model_validate(persisted)
    assert reloaded is not None
    block2 = _MockLLMBlock([])               # no scripted code: LLM use -> error
    second = await block2.process({
        "task": "triple the length", "variables": {"length_m": 7},
        "session": reloaded,
    })
    assert second["status"] == "success"
    assert second["cache_hit"] is True
    assert second["result"] == 21            # cached code re-run with new value
    assert block2.llm_calls == 0             # LLM NOT called
