"""Executable truth table for pi's root-thread context-discipline guard."""

from __future__ import annotations

import json
import os
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
    "tool_name",
    [
        "grep",
        "find",
        "ls",
        "bash",
        "mcp",
        "worktree_commit",
        "worktree_sync",
        "future_tool",
    ],
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
    ("mode", "subagent", "expected"),
    [
        ("tui", False, True),
        ("rpc", False, True),
        ("json", False, False),
        ("print", False, False),
        ("tui", True, False),
    ],
)
def test_plan_mode_excludes_workers(mode: str, subagent: bool, expected: bool) -> None:
    """JSON/print workers and explicitly spawned children cannot enable plan mode."""
    runner = """
import { pathToFileURL } from "node:url";
const module = await import(pathToFileURL(process.argv[1]).href);
console.log(JSON.stringify(module.isPlanModeEnabled(process.argv[2])));
"""
    mode_module = (
        REPO_ROOT / "dot_pi" / "agent" / "extensions" / "plan-mode" / "mode.mjs"
    )
    environment = {**os.environ}
    if subagent:
        environment["PI_SUBAGENT"] = "1"
    else:
        environment.pop("PI_SUBAGENT", None)
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", runner, str(mode_module), mode],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert json.loads(result.stdout) is expected


def test_subagent_child_environment_marks_worker_non_interactive() -> None:
    """The spawn helper used by the extension adds the delegated-child marker."""
    runner = """
import { pathToFileURL } from "node:url";
const module = await import(pathToFileURL(process.argv[1]).href);
console.log(JSON.stringify(module.childEnvironment({ EXISTING: "value" })));
"""
    child_env_module = (
        REPO_ROOT / "dot_pi" / "agent" / "extensions" / "subagent" / "child-env.mjs"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", runner, str(child_env_module)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout) == {"EXISTING": "value", "PI_SUBAGENT": "1"}

    extension = REPO_ROOT / "dot_pi" / "agent" / "extensions" / "subagent" / "index.ts"
    source = extension.read_text()
    assert "execution: agent.execution" in source
    assert "approval: lease" in source
