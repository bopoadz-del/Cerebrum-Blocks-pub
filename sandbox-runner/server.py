"""Sandbox runner — accepts {language, code, input_values, timeout_s}, runs
the code as a subprocess with no parent env, no network access (the
container itself is launched with --network=none), and a per-request
scratch tmpfs at /scratch/<uuid>. Returns stdout/stderr/result/elapsed_ms.

Also exposes ``POST /run_block`` for executing Cerebrum registry blocks
outside the main API process.
"""

from __future__ import annotations

import asyncio
import json
import os
try:
    import resource
except ModuleNotFoundError:  # pragma: no cover - Windows does not have the resource module
    resource = None
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="Cerebrum Sandbox Runner", version="1.0.0", docs_url=None, redoc_url=None)


SCRATCH_ROOT = Path("/scratch")
DEFAULT_TIMEOUT = 10
MAX_TIMEOUT = 30
MAX_OUTPUT_BYTES = 256 * 1024  # 256 KB
MAX_CODE_LEN = 64 * 1024       # 64 KB


class ExecRequest(BaseModel):
    language: str = Field("python", pattern="^(python|bash)$")
    code: str
    input_values: Dict[str, Any] = Field(default_factory=dict)
    timeout_s: int = Field(default=DEFAULT_TIMEOUT, ge=1, le=MAX_TIMEOUT)


class ExecResponse(BaseModel):
    status: str
    result: Optional[Any] = None
    stdout: str
    stderr: str
    elapsed_ms: int
    exit_code: Optional[int] = None
    timed_out: bool = False


class RunBlockRequest(BaseModel):
    block_name: str
    input: Optional[Any] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    timeout_s: int = Field(default=DEFAULT_TIMEOUT, ge=1, le=MAX_TIMEOUT)


class RunBlockResponse(BaseModel):
    status: str
    result: Optional[Any] = None
    stdout: str
    stderr: str
    elapsed_ms: int
    exit_code: Optional[int] = None
    timed_out: bool = False


def _rlimit(memory_mb: int = 256) -> None:
    """Resource limits applied via preexec_fn before the child execs.

    On Windows the ``resource`` module is unavailable, so this is a no-op.
    Operators rely on container-level limits (``--memory``, ``--cpus``) there.
    """
    if resource is None:
        return
    # Address space cap — kills runaway allocators.
    bytes_ = memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (bytes_, bytes_))
    # CPU time wall, slightly above the wall-clock timeout for headroom.
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    # File-descriptor cap.
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    # Process count cap (no fork bombs).
    resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))
    # Stop the child receiving the parent's signals.
    os.setsid()


@app.get("/health")
def health():
    return {"status": "ok", "service": "sandbox-runner"}


@app.post("/exec", response_model=ExecResponse)
async def exec_endpoint(req: ExecRequest) -> ExecResponse:
    if not req.code or not req.code.strip():
        raise HTTPException(400, "code must be non-empty")
    if len(req.code) > MAX_CODE_LEN:
        raise HTTPException(413, f"code exceeds {MAX_CODE_LEN} bytes")

    # Per-request scratch dir under /scratch (operators mount tmpfs there).
    # If /scratch isn't available (e.g. local dev outside docker), fall back
    # to a system temp dir so the runner is still testable.
    try:
        SCRATCH_ROOT.mkdir(exist_ok=True)
        scratch_root = SCRATCH_ROOT
    except (OSError, PermissionError):
        scratch_root = Path(tempfile.gettempdir()) / "sandbox-runner-scratch"
        scratch_root.mkdir(parents=True, exist_ok=True)

    job_dir = scratch_root / uuid.uuid4().hex
    job_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    try:
        if req.language == "python":
            return await _run_python(req, job_dir, started)
        elif req.language == "bash":
            return await _run_bash(req, job_dir, started)
        else:
            raise HTTPException(400, f"unsupported language: {req.language}")
    finally:
        # Best-effort cleanup; operators rely on tmpfs being wiped.
        try:
            for p in job_dir.rglob("*"):
                if p.is_file():
                    p.unlink(missing_ok=True)
            for p in sorted(job_dir.rglob("*"), reverse=True):
                if p.is_dir():
                    p.rmdir()
            job_dir.rmdir()
        except OSError:
            pass


async def _run_python(req: ExecRequest, job_dir: Path, started: float) -> ExecResponse:
    """Wrap the user code in a tiny harness that injects input_values and
    surfaces a `result` variable as JSON on stdout."""
    src = (
        "import json, sys\n"
        f"_inputs = {json.dumps(req.input_values)}\n"
        "globals().update(_inputs)\n"
        "result = None\n"
        f"{req.code}\n"
        "sys.stdout.write('\\n__SANDBOX_RESULT__=' + json.dumps(result, default=str))\n"
    )
    code_path = job_dir / "main.py"
    code_path.write_text(src)

    return await _spawn(
        argv=[sys.executable, "-E", "-S", "-B", str(code_path)],
        cwd=job_dir,
        timeout_s=req.timeout_s,
        started=started,
    )


async def _run_bash(req: ExecRequest, job_dir: Path, started: float) -> ExecResponse:
    """Bash mode runs argv-split-only — never under shell — to avoid
    metacharacter injection. Operators who actually need a shell should
    run a Python wrapper that calls subprocess instead."""
    import shlex
    try:
        argv = shlex.split(req.code)
    except ValueError as e:
        return ExecResponse(
            status="error",
            stdout="",
            stderr=f"shlex parse failed: {e}",
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            exit_code=2,
        )
    if not argv:
        return ExecResponse(
            status="error",
            stdout="",
            stderr="empty argv after shlex parse",
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            exit_code=2,
        )
    return await _spawn(argv=argv, cwd=job_dir, timeout_s=req.timeout_s, started=started)


async def _spawn(*, argv, cwd: Path, timeout_s: int, started: float) -> ExecResponse:
    # Minimal env — the runner already starts with no parent env when launched
    # via docker without --env-file, but we strip explicitly here too.
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
    timed_out = False
    # preexec_fn (and the resource module) are Unix-only.
    popen_kwargs = {"cwd": str(cwd), "env": env, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True}
    if sys.platform != "win32":
        popen_kwargs["preexec_fn"] = _rlimit
    proc = subprocess.Popen(argv, **popen_kwargs)
    try:
        stdout, stderr = await asyncio.get_event_loop().run_in_executor(
            None, lambda: proc.communicate(timeout=timeout_s)
        )
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
        stdout, stderr = proc.communicate()

    stdout = (stdout or "")[:MAX_OUTPUT_BYTES]
    stderr = (stderr or "")[:MAX_OUTPUT_BYTES]

    # Pull __SANDBOX_RESULT__ marker out of stdout for python mode.
    result = None
    marker = "__SANDBOX_RESULT__="
    if marker in stdout:
        head, _, tail = stdout.rpartition(marker)
        try:
            result = json.loads(tail.strip())
            stdout = head.rstrip("\n")
        except json.JSONDecodeError:
            pass

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return ExecResponse(
        status="timeout" if timed_out else ("ok" if proc.returncode == 0 else "error"),
        result=result,
        stdout=stdout,
        stderr=stderr,
        elapsed_ms=elapsed_ms,
        exit_code=proc.returncode,
        timed_out=timed_out,
    )


# ── Block execution endpoint ────────────────────────────────────────────────
# Runs a Cerebrum registry block in a subprocess with a minimal environment.
# The caller (main API) is responsible for deciding *which* blocks must run
# out-of-process based on their manifest capabilities.


BLOCK_REGISTRY_ROOT = Path(os.getenv("BLOCK_REGISTRY_ROOT", "/app/block_registry"))


@app.post("/run_block", response_model=RunBlockResponse)
async def run_block_endpoint(req: RunBlockRequest) -> RunBlockResponse:
    """Execute a registry block adapter in a sandboxed subprocess."""
    if not req.block_name or ".." in req.block_name or "/" in req.block_name:
        raise HTTPException(400, "invalid block_name")

    adapter_path = BLOCK_REGISTRY_ROOT / req.block_name / "block.py"
    if not adapter_path.exists():
        raise HTTPException(404, f"block adapter not found: {req.block_name}")

    payload: Dict[str, Any] = {}
    if req.input is not None:
        payload["input"] = req.input
    if req.params:
        payload.update(req.params)

    # Per-request scratch dir under /scratch (operators mount tmpfs there).
    try:
        SCRATCH_ROOT.mkdir(exist_ok=True)
        scratch_root = SCRATCH_ROOT
    except (OSError, PermissionError):
        scratch_root = Path(tempfile.gettempdir()) / "sandbox-runner-scratch"
        scratch_root.mkdir(parents=True, exist_ok=True)

    job_dir = scratch_root / uuid.uuid4().hex
    job_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    try:
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(BLOCK_REGISTRY_ROOT.parent),
        }
        # If the operator disabled network at the container level, this is a
        # no-op; otherwise it signals the adapter not to make outbound calls.
        if os.getenv("SANDBOX_NETWORK") == "none":
            env["SANDBOX_NETWORK"] = "none"

        popen_kwargs = {
            "cwd": str(job_dir),
            "env": env,
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if sys.platform != "win32":
            popen_kwargs["preexec_fn"] = _rlimit
        proc = subprocess.Popen([sys.executable, str(adapter_path)], **popen_kwargs)
        try:
            stdout, stderr = await asyncio.get_event_loop().run_in_executor(
                None, lambda: proc.communicate(input=json.dumps(payload), timeout=req.timeout_s)
            )
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            stdout, stderr = proc.communicate()
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return RunBlockResponse(
                status="timeout",
                stdout=(stdout or "")[:MAX_OUTPUT_BYTES],
                stderr=(stderr or "")[:MAX_OUTPUT_BYTES],
                elapsed_ms=elapsed_ms,
                exit_code=proc.returncode,
                timed_out=True,
            )

        stdout = (stdout or "")[:MAX_OUTPUT_BYTES]
        stderr = (stderr or "")[:MAX_OUTPUT_BYTES]
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        if proc.returncode != 0:
            return RunBlockResponse(
                status="error",
                stdout=stdout,
                stderr=stderr or f"block exited with code {proc.returncode}",
                elapsed_ms=elapsed_ms,
                exit_code=proc.returncode,
            )

        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            return RunBlockResponse(
                status="error",
                stdout=stdout,
                stderr="invalid JSON output from block adapter",
                elapsed_ms=elapsed_ms,
                exit_code=proc.returncode,
            )

        # The adapter returns {"success": True, "output": {...}} or
        # {"success": False, "error": "..."}.
        if parsed.get("success"):
            return RunBlockResponse(
                status="ok",
                result=parsed.get("output"),
                stdout=stdout,
                stderr=stderr,
                elapsed_ms=elapsed_ms,
                exit_code=proc.returncode,
            )
        return RunBlockResponse(
            status="error",
            result=parsed.get("output"),
            stdout=stdout,
            stderr=parsed.get("error", "block adapter reported failure"),
            elapsed_ms=elapsed_ms,
            exit_code=proc.returncode,
        )
    finally:
        try:
            for p in job_dir.rglob("*"):
                if p.is_file():
                    p.unlink(missing_ok=True)
            for p in sorted(job_dir.rglob("*"), reverse=True):
                if p.is_dir():
                    p.rmdir()
            job_dir.rmdir()
        except OSError:
            pass
