"""Kimi Workbench Block — bounded agent editing with diff + gates.

Scope:
- READS: a brief, a list of mutable file paths, an optional prompt template.
- WRITES: a package containing the diff, changed paths, CLI output, and a gate
  report. It never writes outside the supplied mutable_paths.
- NEVER: executes the changed code, runs network operations itself, or mutates
  paths that were not explicitly listed.

The block snapshots the mutable paths, invokes the Kimi CLI with a prompt,
then snapshots again. The resulting diff is passed through deterministic gates
(syntax check for Python, safety scan). If any gate fails, the package still
contains the diff but is marked as not promotable.
"""

from __future__ import annotations

import ast
import asyncio
import difflib
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.typed_block import TypedBlock, Schema, ContentType

logger = logging.getLogger(__name__)


# Safety patterns borrowed from the validation block. These are deliberately
# conservative: anything that looks like shell execution, dynamic code, or
# unsafe deserialization is flagged for human review.
_SAFETY_PATTERNS = {
    "shell_execution": r"(?:os\.system|subprocess\.(call|run|Popen)|subprocess\.call)",
    "eval_usage": r"\beval\s*\(",
    "exec_usage": r"\bexec\s*\(",
    "dynamic_import": r"__import__\s*\(",
    "pickle_loads": r"pickle\.loads?\s*\(",
    "yaml_unsafe": r"yaml\.load\s*\([^)]*\)",
}


class WorkbenchBlock(TypedBlock):
    """Bounded Kimi CLI workbench: prompt → edit → diff → gates → package."""

    name = "workbench"
    version = "1.0.0"
    description = (
        "Invokes the Kimi CLI with a brief, captures edits inside mutable_paths, "
        "and returns a diff plus validation gate report."
    )
    layer = 3
    tags = ["workbench", "agent", "kimi", "diff", "gates", "code"]
    requires = []

    input_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=["brief", "mutable_paths"],
        optional_fields=["prompt_template", "timeout_seconds"],
        format_hints={},
    )

    output_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=["status"],
        optional_fields=[
            "result",
            "diff",
            "changed_paths",
            "gate_report",
            "cli_stdout",
            "cli_stderr",
            "error",
        ],
        format_hints={},
    )

    default_config = {
        "kimi_cli_path": os.getenv("KIMI_CLI_PATH", "kimi"),
        "timeout_seconds": 300,
        "default_prompt_template": None,
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"brief": "...", "mutable_paths": ["..."]}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "diff", "type": "text", "label": "Diff"},
                {"name": "gate_report", "type": "json", "label": "Gate Report"},
                {"name": "changed_paths", "type": "json", "label": "Changed Paths"},
            ],
        },
        "params": [
            {"name": "action", "type": "select", "label": "Action", "options": ["run"], "default": "run"},
        ],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block=hal_block, config=config)
        # Test seam: replace with a fake runner that returns
        # {"returncode": int, "stdout": str, "stderr": str}.
        self._cli_runner: Optional[Any] = None

    async def process(self, input_data: Dict, params: Dict = None) -> Dict:
        """Run the workbench agent."""
        params = params or {}
        action = params.get("action", "run")
        if action != "run":
            return {"status": "error", "error": f"Unknown action: {action}"}

        data = input_data if isinstance(input_data, dict) else {}
        brief = data.get("brief")
        mutable_paths = data.get("mutable_paths")

        if not brief:
            return {"status": "error", "error": "Missing required field: brief"}
        if not mutable_paths:
            return {"status": "error", "error": "Missing required field: mutable_paths"}
        if not isinstance(mutable_paths, list):
            return {"status": "error", "error": "mutable_paths must be a list"}

        # Resolve and validate all paths before touching anything.
        resolved = []
        for raw in mutable_paths:
            path = Path(raw).resolve()
            if not path.exists():
                return {"status": "error", "error": f"Mutable path does not exist: {path}"}
            resolved.append(path)

        # Work inside a temp directory that contains the mutable paths as a
        # bounded workspace. We symlink files in rather than copy the whole tree,
        # so the CLI sees a clean, isolated workspace.
        workspace = Path(tempfile.mkdtemp(prefix="kimi-workbench-"))
        try:
            for src in resolved:
                link_name = workspace / src.name
                if src.is_dir():
                    # Use junction on Windows when symlinks require privileges.
                    try:
                        os.symlink(src, link_name, target_is_directory=True)
                    except OSError:
                        shutil.copytree(src, link_name)
                else:
                    try:
                        os.symlink(src, link_name)
                    except OSError:
                        shutil.copy2(src, link_name)

            before = self._snapshot(workspace, resolved)

            prompt_template = (
                data.get("prompt_template")
                or self.config.get("default_prompt_template")
                or self._default_prompt_template()
            )
            prompt = prompt_template.format(
                brief=brief,
                mutable_paths="\n".join(str(p) for p in resolved),
            )
            prompt_file = workspace / "kimi_prompt.md"
            prompt_file.write_text(prompt, encoding="utf-8")

            timeout = float(
                data.get("timeout_seconds")
                or self.config.get("timeout_seconds", 300)
            )
            cli_path = self.config.get("kimi_cli_path", "kimi")

            # --prompt already implies auto permission mode; --yolo/--auto are
            # mutually exclusive with it and the real CLI rejects the combination.
            cmd = [
                cli_path,
                "--prompt",
                f"@{prompt_file}",
                "--add-dir",
                str(workspace),
            ]

            logger.info("workbench: invoking Kimi CLI for brief: %s", brief[:80])
            if self._cli_runner:
                proc_result = self._cli_runner(cmd, str(workspace), timeout)
            else:
                proc_result = await self._run_cli(cmd, str(workspace), timeout)

            cli_stdout = proc_result.get("stdout", "")
            cli_stderr = proc_result.get("stderr", "")

            if proc_result.get("returncode", -1) != 0:
                return {
                    "status": "error",
                    "error": f"Kimi CLI failed (exit {proc_result.get('returncode')}): {cli_stderr or cli_stdout}".strip(),
                    "cli_stdout": cli_stdout,
                    "cli_stderr": cli_stderr,
                }

            after = self._snapshot(workspace, resolved)
            diff = self._compute_diff(before, after)
            changed_paths = sorted(
                {p for p in diff.keys() if diff[p]["before"] != diff[p]["after"]}
            )

            gate_report = self._run_gates(workspace, changed_paths)
            promotable = all(g.get("pass") for g in gate_report.values())
            if not changed_paths:
                gate_report["non_empty_diff"] = {
                    "pass": False,
                    "reason": "no files changed — CLI produced an empty diff",
                }
                promotable = False

            return {
                "status": "success",
                "result": {
                    "diff": self._format_unified_diff(diff),
                    "changed_paths": changed_paths,
                    "gate_report": gate_report,
                    "promotable": promotable,
                    "cli_stdout": cli_stdout,
                    "cli_stderr": cli_stderr,
                    "workspace": str(workspace),
                },
            }
        finally:
            # Clean up the temp workspace; the real mutable paths are the sources.
            try:
                shutil.rmtree(workspace, ignore_errors=True)
            except Exception:
                pass

    def _default_prompt_template(self) -> str:
        return (
            "You are a careful coding assistant operating inside a bounded workbench.\n\n"
            "Brief:\n{brief}\n\n"
            "You may read and edit ONLY the files listed below. Do not create new files, "
            "do not run shell commands, and do not execute code. After editing, briefly "
            "summarize what changed.\n\n"
            "Mutable paths:\n{mutable_paths}\n"
        )

    def _snapshot(self, workspace: Path, sources: List[Path]) -> Dict[str, str]:
        """Return a map of relative path -> content for every mutable path."""
        snapshot: Dict[str, str] = {}
        for src in sources:
            link = workspace / src.name
            if link.is_dir():
                for path in link.rglob("*"):
                    if path.is_file():
                        rel = path.relative_to(workspace).as_posix()
                        try:
                            snapshot[rel] = path.read_text(encoding="utf-8")
                        except UnicodeDecodeError:
                            snapshot[rel] = ""
            else:
                rel = link.relative_to(workspace).as_posix()
                try:
                    snapshot[rel] = link.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    snapshot[rel] = ""
        return snapshot

    def _compute_diff(self, before: Dict[str, str], after: Dict[str, str]) -> Dict[str, Dict[str, str]]:
        """Return per-path before/after maps."""
        all_paths = set(before.keys()) | set(after.keys())
        return {p: {"before": before.get(p, ""), "after": after.get(p, "")} for p in all_paths}

    def _format_unified_diff(self, diff: Dict[str, Dict[str, str]]) -> str:
        lines: List[str] = []
        for path in sorted(diff.keys()):
            before = diff[path]["before"].splitlines(keepends=True)
            after = diff[path]["after"].splitlines(keepends=True)
            if before == after:
                continue
            # Ensure lines end with newline for difflib.
            before = [ln if ln.endswith("\n") else ln + "\n" for ln in before] or ["\n"]
            after = [ln if ln.endswith("\n") else ln + "\n" for ln in after] or ["\n"]
            lines.extend(
                difflib.unified_diff(
                    before,
                    after,
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )
        return "".join(lines)

    def _run_gates(self, workspace: Path, changed_paths: List[str]) -> Dict[str, Any]:
        """Run deterministic gates on changed files."""
        gate_report: Dict[str, Any] = {
            "syntax_check": {"pass": True, "reason": "no changed Python files"},
            "safety_scan": {"pass": True, "reason": "no dangerous patterns found"},
        }

        python_files = [p for p in changed_paths if p.endswith(".py")]
        if not python_files:
            return gate_report

        syntax_errors: List[str] = []
        for rel in python_files:
            path = workspace / rel
            try:
                source = path.read_text(encoding="utf-8")
            except Exception as exc:
                syntax_errors.append(f"{rel}: {exc}")
                continue
            try:
                ast.parse(source)
            except SyntaxError as exc:
                syntax_errors.append(f"{rel}:{exc.lineno}: {exc.msg}")

        if syntax_errors:
            gate_report["syntax_check"] = {
                "pass": False,
                "reason": "syntax errors detected",
                "findings": syntax_errors,
            }

        findings: Dict[str, List[str]] = {}
        for rel in python_files:
            path = workspace / rel
            try:
                source = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for name, pattern in _SAFETY_PATTERNS.items():
                matches = re.findall(pattern, source)
                if matches:
                    findings.setdefault(name, []).append(rel)

        if findings:
            gate_report["safety_scan"] = {
                "pass": False,
                "reason": "dangerous patterns detected",
                "findings": findings,
            }

        return gate_report

    async def _run_cli(self, cmd: List[str], cwd: str, timeout: float) -> Dict[str, Any]:
        """Run the Kimi CLI in a subprocess and capture output."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            stdout, stderr = await proc.communicate()
            return {
                "returncode": -1,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": f"Timed out after {timeout}s\n" + stderr.decode("utf-8", errors="replace"),
            }

        return {
            "returncode": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
