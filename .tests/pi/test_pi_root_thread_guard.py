"""Executable truth table for pi's root-thread context-discipline guard."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE = REPO_ROOT / "dot_pi" / "agent" / "extensions" / "root-thread-guard-core.mjs"
NODE_RUNNER = """
import { pathToFileURL } from "node:url";
const core = await import(pathToFileURL(process.argv[1]).href);
const cases = JSON.parse(process.argv[2]);
console.log(JSON.stringify(cases.map((item) => core.decideToolCall(item))));
"""


def decide(cases: list[dict]) -> list[dict]:
    """Run the actual JavaScript policy module under Node."""
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "--eval",
            NODE_RUNNER,
            str(CORE),
            json.dumps(cases),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "tool_name",
    [
        "subagent",
        "write",
        "edit",
        "questionnaire",
        "plan_write",
        "scratchpad",
        "worktree_start",
        "memory_search",
    ],
)
def test_root_allowlist(tool_name: str, tmp_path: Path) -> None:
    result = decide([{"mode": "tui", "toolName": tool_name, "cwd": str(tmp_path)}])[0]
    assert result["allowed"] is True


@pytest.mark.parametrize(
    "tool_name", ["grep", "find", "ls", "bash", "mcp", "future_tool"]
)
def test_root_blocks_exploration_and_unknown_tools(
    tool_name: str, tmp_path: Path
) -> None:
    result = decide([{"mode": "rpc", "toolName": tool_name, "cwd": str(tmp_path)}])[0]
    assert result["allowed"] is False
    assert "Delegate" in result["reason"]


@pytest.mark.parametrize("mode", ["json", "print"])
def test_worker_and_one_shot_modes_are_exempt(mode: str, tmp_path: Path) -> None:
    result = decide([{"mode": mode, "toolName": "mcp", "cwd": str(tmp_path)}])[0]
    assert result["allowed"] is True


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("~/agent/plans/current.md", True),
        ("~/agent/memory/MEMORY.md", True),
        ("todo.txt", True),
        ("done.txt", True),
        ("README.md", False),
        ("todo.txt/child", False),
    ],
)
def test_read_is_limited_to_scratch_paths(
    path: str, allowed: bool, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    result = decide(
        [
            {
                "mode": "tui",
                "toolName": "read",
                "input": {"path": path},
                "cwd": str(tmp_path),
                "home": str(home),
                "agentDir": str(home / "agent"),
            }
        ]
    )[0]
    assert result["allowed"] is allowed


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("tui", True), ("rpc", True), ("json", False), ("print", False)],
)
def test_plan_mode_is_interactive_root_only(mode: str, expected: bool) -> None:
    """JSON workers and print one-shots must never enter read-only plan mode."""
    runner = """
import { pathToFileURL } from "node:url";
const module = await import(pathToFileURL(process.argv[1]).href);
console.log(JSON.stringify(module.isInteractiveRootMode(process.argv[2])));
"""
    mode_module = (
        REPO_ROOT / "dot_pi" / "agent" / "extensions" / "plan-mode" / "mode.mjs"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", runner, str(mode_module), mode],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout) is expected
