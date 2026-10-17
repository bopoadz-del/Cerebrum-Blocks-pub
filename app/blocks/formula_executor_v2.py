"""Formula Executor v2 — LLM code generation + sandboxed execution.

Reasoning Engine Plan 4. Supersedes the pattern-matching FormulaExecutorBlock.

Flow: build prompt -> LLM writes Python -> run in the Plan-3 sandbox ->
cache a success on the session -> retry with the error message on a failure.

Sandbox contract note: Plan 3's ``run_sandboxed`` has NO ``timeout_seconds``
parameter and no internal timeout. To keep the configurable ``timeout_seconds``
behaviour the plan asks for, each sandbox call is run in a daemon worker thread
joined with a timeout (see ``_run_sandboxed_with_timeout``). A genuinely
runaway snippet leaves the daemon thread orphaned but cannot block the process;
RestrictedPython already bars I/O and dangerous builtins.
"""

import os
import re
import threading
from typing import Any, Dict, Optional

import httpx

from app.core.universal_base import UniversalBlock
from app.core.sandbox import run_sandboxed, SandboxResult
from app.core.formula_definitions import (
    definitions_prompt_block,
    grounding_report,
    load_definitions,
    match_definitions,
    not_assessed,
)

from app.prompts.codegen_system import build_codegen_prompt
from app.core.http_errors import mark_unavailable

_FENCE_RE = re.compile(r"```(?:python)?\s*(.*?)\s*```", re.DOTALL)


def _strip_fences(text: str) -> str:
    """Pull the code out of a ```python ...``` block; return text as-is if
    the LLM did not fence it."""
    m = _FENCE_RE.search(text or "")
    return (m.group(1) if m else (text or "")).strip()


def _cache_key(task: str, variables: Dict[str, Any]) -> str:
    """Stable key for a code-gen request: the task plus the sorted variable
    NAMES (not values — cached code is re-run with fresh values)."""
    names = ",".join(sorted(variables))
    return f"{task.strip().lower()}|{names}"


def _error(
    message: str,
    *,
    attempts: int = 0,
    generated_code: str = "",
    traceback: Optional[str] = None,
    error_type: Optional[str] = None,
    task: str = "",
    grounding: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build an error result with the FULL key set every error path emits.

    The three error exits in ``process()`` previously returned inconsistent
    keys, so a caller doing ``out["generated_code"]`` could KeyError depending
    on which failure fired. This helper guarantees a uniform shape; the
    ``traceback`` key is always present (a test asserts on it)."""
    return {
        "status": "error",
        "error": message,
        "generated_code": generated_code,
        "traceback": traceback if traceback is not None else message,
        "error_type": error_type,
        "attempts": attempts,
        "task": task,
        # Present on EVERY exit. Adding it to the success paths alone
        # reintroduced the exact defect this helper exists to prevent: a
        # caller reading result["grounding"] would KeyError depending on
        # which failure fired.
        "grounding": grounding
        or not_assessed("the calculation did not complete, so nothing was grounded"),
    }


def _run_sandboxed_with_timeout(
    code: str, variables: Dict[str, Any], timeout_seconds: int
) -> SandboxResult:
    """Run ``run_sandboxed`` in a daemon thread joined with ``timeout_seconds``.

    The Plan-3 sandbox has no native timeout, so this wrapper supplies one.
    On timeout a synthetic failed :class:`SandboxResult` is returned and the
    worker thread is left to finish on its own (it cannot touch the host).
    """
    box: Dict[str, SandboxResult] = {}

    def _worker() -> None:
        box["result"] = run_sandboxed(code, state=variables)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    if thread.is_alive():
        return SandboxResult(
            success=False,
            error=f"Execution timed out after {timeout_seconds}s",
            error_type="TimeoutError",
        )
    return box.get(
        "result",
        SandboxResult(
            success=False,
            error="Sandbox produced no result",
            error_type="RuntimeError",
        ),
    )


class FormulaExecutorV2Block(UniversalBlock):
    name = "formula_executor_v2"
    version = "2.0.0"
    description = (
        "LLM code-generation for deterministic, auditable domain calculations; "
        "generated Python runs inside the restricted sandbox."
    )
    layer = 3
    tags = [
        "domain",
        "reasoning",
        "calculation",
        "codegen",
        "llm",
        "sandbox",
        "deterministic",
        "auditable",
    ]
    requires = []

    default_config = {
        "max_retries": 2,        # extra attempts after the first
        "timeout_seconds": 10,
        "model": "kimi-k2-0905-preview",
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"task": "concrete volume for a 10x8m slab 0.2m thick", "variables": {"length_m": 10, "width_m": 8, "thickness_m": 0.2}}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "generated_code", "type": "code", "label": "Generated Code"},
                {"name": "result", "type": "text", "label": "Result"},
                # Surfaced beside the number, not filed in an audit log. A
                # reader must be able to see "this came from the platform's
                # definition" or "the model derived this" without leaving the
                # answer.
                {"name": "grounding", "type": "json", "label": "Grounding"},
                {"name": "attempts", "type": "number", "label": "Attempts"},
            ],
        },
        "quick_actions": [
            {"icon": "", "label": "Calculate", "prompt": "Calculate concrete volume for a 10x8m slab, 200mm thick"},
        ],
    }

    async def _call_llm(self, prompt: str) -> str:
        """Send the code-gen prompt to Kimi (Moonshot) and return the reply.

        Routes via app.core.llm_config (the platform's single Kimi provider).
        Overridden by test doubles. Raises RuntimeError when no key is set so
        callers get a clear, non-secret error.
        """
        from app.core.llm_config import _llm_config  # local import: avoid cycle at module load
        cfg = _llm_config()
        api_key = os.getenv(cfg["env_key"])
        if not api_key:
            raise mark_unavailable(RuntimeError(f"{cfg['env_key']} not configured"))
        model = self.config.get("model") or cfg["default_model"]
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                cfg["url"],
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,   # deterministic code generation
                },
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"{cfg['provider']} API error (HTTP {resp.status_code})"
                )
            return resp.json()["choices"][0]["message"]["content"]

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        # InputAdapter wraps a bare string as {"text": "..."}; accept that and
        # the legacy {"input": "..."} shape as the task description too.
        task = data.get("task") or data.get("formula_description") \
            or data.get("text") or data.get("input") \
            or params.get("task") \
            or (str(input_data) if not isinstance(input_data, dict) else "")
        variables = dict(data.get("variables") or data.get("input_values") or {})

        if not task.strip():
            return _error("No task description provided")

        timeout_seconds = int(self.config.get("timeout_seconds", 10))
        session = data.get("session") or params.get("session")
        key = _cache_key(task, variables)

        # --- grounding ------------------------------------------------------
        # Resolved once and attached to every success, including cache hits: a
        # cached answer is exactly as grounded (or as invented) as the answer
        # that was cached, and a result whose provenance disappears on the
        # second call is worse than one that never claimed any.
        definitions = load_definitions()
        matched = match_definitions(task, definitions)
        grounding = grounding_report(task, definitions)
        definitions_block = definitions_prompt_block(matched)

        # --- cache hit: re-run the previously generated code, skip the LLM --
        if session is not None and key in session.code_cache:
            cached_code = session.code_cache[key]
            sandbox = _run_sandboxed_with_timeout(
                cached_code, variables, timeout_seconds,
            )
            if sandbox.success:
                return {
                    "status": "success",
                    "generated_code": cached_code,
                    "result": sandbox.result,
                    "stdout": sandbox.stdout,
                    "attempts": 0,
                    "cache_hit": True,
                    "task": task,
                    "grounding": grounding,
                }
            # stale cache (e.g. variable set changed) — fall through to regen

        # --- generate -> run -> retry loop ---------------------------------
        max_attempts = 1 + int(self.config.get("max_retries", 2))
        prior_code: Optional[str] = None
        prior_error: Optional[str] = None
        last_code = ""
        last_error_type: Optional[str] = None
        last_error = "Code generation failed"

        for attempt in range(1, max_attempts + 1):
            prompt = build_codegen_prompt(
                task, variables,
                prior_code=prior_code, prior_error=prior_error,
                definitions_block=definitions_block,
            )
            try:
                raw = await self._call_llm(prompt)
            except Exception as e:
                # Transient LLM/network failure: record and retry until
                # ``max_attempts`` is exhausted, then surface the last error.
                last_error = f"Code generation failed: {e}"
                last_error_type = type(e).__name__
                prior_error = str(e)
                if attempt < max_attempts:
                    continue
                return _error(
                    last_error,
                    generated_code=last_code,
                    traceback=last_error,
                    error_type=last_error_type,
                    attempts=attempt,
                    task=task,
                    grounding=grounding,
                )

            code = _strip_fences(raw)
            last_code = code
            sandbox = _run_sandboxed_with_timeout(
                code, variables, timeout_seconds,
            )
            if sandbox.success:
                if session is not None:
                    # Caching contract: this mutates the SAME ProjectSession
                    # object the caller passed in (threaded by reference
                    # reasoner -> plan_executor -> here). The caller MUST call
                    # ``store.save(session)`` after ``process()`` returns for
                    # this write to persist — process() does not save itself.
                    # See app/routers/project.py::project_ask for the real
                    # round trip.
                    session.code_cache[key] = code
                return {
                    "status": "success",
                    "generated_code": code,
                    "result": sandbox.result,
                    "stdout": sandbox.stdout,
                    "attempts": attempt,
                    "cache_hit": False,
                    "task": task,
                    "grounding": grounding,
                }
            # failed — carry context into the next attempt
            last_error = sandbox.error or "Sandbox execution failed"
            last_error_type = sandbox.error_type
            prior_code = code
            prior_error = sandbox.error or last_error

        return _error(
            last_error,
            generated_code=last_code,
            traceback=last_error,
            error_type=last_error_type,
            attempts=max_attempts,
            task=task,
            grounding=grounding,
        )
