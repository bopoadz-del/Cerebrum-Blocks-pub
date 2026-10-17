"""Code Block - Sandboxed Python execution via subprocess + AST analysis"""

import ast
import logging
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

logger = logging.getLogger(__name__)

_TIMEOUT = 10  # seconds
_MAX_OUTPUT = 10_000

_DANGEROUS_PATTERNS = [
    "os.system", "subprocess", "shutil.rmtree", "__import__",
    "open(", "os.remove", "os.unlink", "socket.connect",
]


def _syntax_check(code: str) -> str | None:
    try:
        ast.parse(code)
        return None
    except SyntaxError as e:
        return f"SyntaxError at line {e.lineno}: {e.msg}"


def _analyze(code: str) -> Dict:
    issues = []
    for pat in _DANGEROUS_PATTERNS:
        if pat in code:
            issues.append(f"Potentially unsafe: {pat}")

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"valid": False, "error": str(e), "error_kind": error_kind(e), "issues": issues}

    imports = [
        node.names[0].name if hasattr(node, "names") and node.names else ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    funcs = [
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    ]
    classes = [
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ]
    lines = code.splitlines()

    return {
        "valid": True,
        "lines": len(lines),
        "imports": list(set(filter(None, imports))),
        "functions": funcs,
        "classes": classes,
        "issues": issues,
    }


def _run_python(code: str, timeout: int) -> Dict:
    syntax_err = _syntax_check(code)
    if syntax_err:
        return {"status": "error", "error": syntax_err, "output": "", "exit_code": 1}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        tmpfile = f.name

    try:
        start = time.monotonic()
        proc = subprocess.run(
            [sys.executable, tmpfile],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        stdout = proc.stdout[:_MAX_OUTPUT]
        stderr = proc.stderr[:2000]

        return {
            "status": "success" if proc.returncode == 0 else "error",
            "output": stdout,
            "stderr": stderr if stderr else None,
            "exit_code": proc.returncode,
            "execution_time_ms": elapsed_ms,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"Execution timed out after {timeout}s", "output": ""}
    except Exception as e:
        return {"status": "error", "error": str(e), "error_kind": error_kind(e), "output": ""}
    finally:
        try:
            os.unlink(tmpfile)
        except OSError:
            pass


def _run_node(code: str, timeout: int) -> Dict:
    node_bin = "node"
    if subprocess.run(["which", node_bin], capture_output=True).returncode != 0:
        return {"status": "error", "error": "Node.js not available on this server"}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write(code)
        tmpfile = f.name

    try:
        start = time.monotonic()
        proc = subprocess.run(
            [node_bin, tmpfile],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "status": "success" if proc.returncode == 0 else "error",
            "output": proc.stdout[:_MAX_OUTPUT],
            "stderr": proc.stderr[:2000] or None,
            "exit_code": proc.returncode,
            "execution_time_ms": elapsed_ms,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"Execution timed out after {timeout}s", "output": ""}
    finally:
        try:
            os.unlink(tmpfile)
        except OSError:
            pass


class CodeBlock(UniversalBlock):
    """Python and JavaScript code execution with static analysis"""

    name = "code"
    version = "2.0"
    description = "Execute Python or JavaScript code; analyze code for issues"
    layer = 3
    tags = ["domain", "code", "execution"]
    requires = []

    ui_schema = {
        "input": {
            "type": "code",
            "accept": None,
            "placeholder": "Paste code to execute or describe code to analyze...",
            "multiline": True,
        },
        "output": {
            "type": "code",
            "fields": [
                {"name": "output", "type": "code", "label": "Result"},
                {"name": "language", "type": "text", "label": "Language"},
                {"name": "execution_time_ms", "type": "number", "label": "Time (ms)"},
            ],
        },
        "quick_actions": [
            {"icon": "🐍", "label": "Python", "prompt": "Write Python code to"},
            {"icon": "📜", "label": "JavaScript", "prompt": "Write JavaScript code to"},
        ],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}

        code = ""
        if isinstance(input_data, str):
            code = input_data
        elif isinstance(input_data, dict):
            code = (input_data.get("code") or input_data.get("text") or
                    input_data.get("input") or params.get("code", ""))
        else:
            code = params.get("code", "")

        language = params.get("language", "python").lower()
        operation = params.get("operation", "execute")
        timeout = min(int(params.get("timeout", _TIMEOUT)), 30)

        if not code or not code.strip():
            return {"status": "error", "error": "No code provided"}

        if operation == "analyze":
            analysis = _analyze(code)
            return {
                "status": "success",
                "operation": "analyze",
                "language": language,
                **analysis,
            }

        # execute
        if language in ("python", "py"):
            sandbox_url = os.getenv("SANDBOX_RUNNER_URL")
            if sandbox_url:
                runner_result = await self._exec_via_runner(
                    sandbox_url,
                    language="python",
                    code=code,
                    input_values=params.get("input_values", {}) if isinstance(params.get("input_values", {}), dict) else {},
                    timeout_s=timeout,
                )
                if runner_result is not None:
                    result = runner_result
                else:
                    # Network/HTTP failure — fall back to in-process so the
                    # caller never sees a 500 just because the runner is down.
                    result = _run_python(code, timeout)
            else:
                result = _run_python(code, timeout)
        elif language in ("javascript", "js", "node"):
            result = _run_node(code, timeout)
        else:
            return {
                "status": "error",
                "error": f"Unsupported language: {language}. Supported: python, javascript",
            }

        return {
            **result,
            "language": language,
            "operation": operation,
            "lines_executed": len(code.splitlines()),
        }

    async def _exec_via_runner(
        self,
        url: str,
        *,
        language: str,
        code: str,
        input_values: Dict,
        timeout_s: int,
    ):
        """POST to the sandbox runner. Returns a dict matching this block's
        existing _run_python output shape on success, or None on network /
        HTTP errors so the caller can fall back to in-process."""
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not installed; cannot use SANDBOX_RUNNER_URL")
            return None

        payload = {
            "language": language,
            "code": code,
            "input_values": input_values or {},
            "timeout_s": timeout_s,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout_s + 5) as client:
                resp = await client.post(f"{url.rstrip('/')}/exec", json=payload)
        except (httpx.HTTPError, OSError) as e:
            logger.warning("sandbox runner network error: %s; falling back to in-process", e)
            return None

        if resp.status_code != 200:
            logger.warning(
                "sandbox runner returned %s; falling back to in-process",
                resp.status_code,
            )
            return None

        try:
            data = resp.json()
        except ValueError:
            logger.warning("sandbox runner returned non-JSON; falling back")
            return None

        # Translate runner shape -> code-block shape
        runner_status = data.get("status")
        return {
            "status": "success" if runner_status == "ok" else "error",
            "output": data.get("stdout", ""),
            "stderr": data.get("stderr") or None,
            "exit_code": data.get("exit_code"),
            "execution_time_ms": data.get("elapsed_ms", 0),
            "result": data.get("result"),
            "error": (
                f"Execution timed out after {timeout_s}s"
                if data.get("timed_out") else
                (None if runner_status == "ok" else data.get("stderr") or "execution error")
            ),
        }
