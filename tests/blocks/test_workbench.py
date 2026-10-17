"""Tests for the Kimi workbench block.

The workbench block invokes the Kimi CLI with a prompt, lets it edit files
inside a bounded set of mutable paths, captures the resulting diff, and runs
validation gates before returning a package.
"""

import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.blocks.workbench import WorkbenchBlock


@pytest.fixture
def workbench():
    return WorkbenchBlock(config={})


def _assert_legal_kimi_argv(cmd: List[str]) -> None:
    """Reject argv combinations the real Kimi CLI refuses at startup.

    ``--prompt`` implies auto permission mode; ``--yolo`` and ``--auto`` are
    mutually exclusive with it (and with each other).
    """
    flags = set(cmd)
    if "--prompt" in flags and ({"--yolo", "--auto"} & flags):
        raise AssertionError(f"illegal Kimi argv: --prompt with --yolo/--auto: {cmd}")
    if "--yolo" in flags and "--auto" in flags:
        raise AssertionError(f"illegal Kimi argv: --yolo with --auto: {cmd}")


def _block_with_runner(runner):
    block = WorkbenchBlock(config={})
    block._cli_runner = runner
    return block


@pytest.mark.asyncio
async def test_workbench_invokes_cli_with_prompt_and_mutable_paths(workbench):
    """The CLI is called with a prompt file and the mutable path workspace."""
    calls: List[Dict[str, Any]] = []

    def fake_runner(cmd: List[str], cwd: str, timeout: float) -> Dict[str, Any]:
        _assert_legal_kimi_argv(cmd)
        calls.append({"cmd": cmd, "cwd": cwd, "timeout": timeout})
        # Simulate Kimi editing a file by writing to the mutable path.
        mutable = Path(cwd)
        (mutable / "module.py").write_text("x = 1\n", encoding="utf-8")
        return {"returncode": 0, "stdout": "done", "stderr": ""}

    workbench._cli_runner = fake_runner

    with tempfile.TemporaryDirectory() as tmp:
        module = Path(tmp) / "module.py"
        module.write_text("x = 0\n", encoding="utf-8")

        result = await workbench.process(
            {
                "brief": "Set x to 1",
                "mutable_paths": [str(module)],
            }
        )

    assert result["status"] == "success"
    assert len(calls) == 1
    call = calls[0]
    assert "kimi" in call["cmd"][0]
    assert any("--add-dir" in arg for arg in call["cmd"])
    add_dir_index = call["cmd"].index("--add-dir")
    workspace_arg = call["cmd"][add_dir_index + 1]
    assert Path(workspace_arg).is_absolute()


@pytest.mark.asyncio
async def test_workbench_captures_diff_after_edit():
    """The returned package contains a diff of changed mutable paths."""

    def fake_runner(cmd: List[str], cwd: str, timeout: float) -> Dict[str, Any]:
        module = Path(cwd) / "module.py"
        module.write_text("def answer():\n    return 42\n", encoding="utf-8")
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    with tempfile.TemporaryDirectory() as tmp:
        module = Path(tmp) / "module.py"
        module.write_text("def answer():\n    return 0\n", encoding="utf-8")

        block = _block_with_runner(fake_runner)
        result = await block.process(
            {
                "brief": "Return 42",
                "mutable_paths": [str(module)],
            }
        )

    assert result["status"] == "success"
    package = result["result"]
    assert package["diff"]
    assert "-    return 0" in package["diff"]
    assert "+    return 42" in package["diff"]
    assert package["changed_paths"] == ["module.py"]


@pytest.mark.asyncio
async def test_workbench_runs_validation_gate_on_changed_python():
    """A changed Python file is syntax-checked and scanned for dangerous calls."""

    def fake_runner(cmd: List[str], cwd: str, timeout: float) -> Dict[str, Any]:
        module = Path(cwd) / "module.py"
        module.write_text("print('hello')\n", encoding="utf-8")
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    with tempfile.TemporaryDirectory() as tmp:
        module = Path(tmp) / "module.py"
        module.write_text("# placeholder\n", encoding="utf-8")

        block = _block_with_runner(fake_runner)
        result = await block.process(
            {
                "brief": "Add a print",
                "mutable_paths": [str(module)],
            }
        )

    assert result["status"] == "success"
    gate_report = result["result"]["gate_report"]
    assert gate_report["syntax_check"]["pass"] is True
    assert gate_report["safety_scan"]["pass"] is True


@pytest.mark.asyncio
async def test_workbench_blocks_dangerous_edit():
    """An edit introducing eval/exec/subprocess is flagged by the safety gate."""

    def fake_runner(cmd: List[str], cwd: str, timeout: float) -> Dict[str, Any]:
        module = Path(cwd) / "module.py"
        module.write_text(
            "import os; os.system('rm -rf /')\n", encoding="utf-8"
        )
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    with tempfile.TemporaryDirectory() as tmp:
        module = Path(tmp) / "module.py"
        module.write_text("# safe\n", encoding="utf-8")

        block = _block_with_runner(fake_runner)
        result = await block.process(
            {
                "brief": "Do something unsafe",
                "mutable_paths": [str(module)],
            }
        )

    assert result["status"] == "success"
    gate_report = result["result"]["gate_report"]
    assert gate_report["safety_scan"]["pass"] is False
    assert "shell_execution" in gate_report["safety_scan"]["findings"]


@pytest.mark.asyncio
async def test_workbench_requires_mutable_paths(workbench):
    """Missing mutable_paths is rejected up front."""
    result = await workbench.process({"brief": "No paths given"})
    assert result["status"] == "error"
    assert "mutable_paths" in result["error"].lower()


@pytest.mark.asyncio
async def test_workbench_reports_cli_failure():
    """A non-zero CLI exit is surfaced as an error with stderr."""

    def fake_runner(cmd: List[str], cwd: str, timeout: float) -> Dict[str, Any]:
        return {"returncode": 1, "stdout": "", "stderr": "auth required"}

    with tempfile.TemporaryDirectory() as tmp:
        module = Path(tmp) / "module.py"
        module.write_text("x = 0\n", encoding="utf-8")

        block = _block_with_runner(fake_runner)
        result = await block.process(
            {
                "brief": "Change x",
                "mutable_paths": [str(module)],
            }
        )

    assert result["status"] == "error"
    assert "auth required" in result["error"]


@pytest.mark.asyncio
async def test_workbench_empty_diff_is_not_promotable():
    """A CLI session that edits nothing must not be promotable."""

    def fake_runner(cmd: List[str], cwd: str, timeout: float) -> Dict[str, Any]:
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    with tempfile.TemporaryDirectory() as tmp:
        module = Path(tmp) / "module.py"
        module.write_text("x = 0\n", encoding="utf-8")

        block = _block_with_runner(fake_runner)
        result = await block.process(
            {
                "brief": "Do nothing",
                "mutable_paths": [str(module)],
            }
        )

    assert result["status"] == "success"
    package = result["result"]
    assert package["changed_paths"] == []
    assert package["promotable"] is False
    assert package["gate_report"]["non_empty_diff"]["pass"] is False
