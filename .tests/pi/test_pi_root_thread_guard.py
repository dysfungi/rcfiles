"""Executable truth table for pi's root-thread context-discipline guard."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGED_ROOT = REPO_ROOT / "home"
CORE = MANAGED_ROOT / "dot_pi" / "agent" / "extensions" / "root-thread-guard-core.mjs"
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
    ("path", "allowed"),
    [
        ("~/.pi/agent/skills/nested/example/SKILL.md", True),
        ("~/.agents/skills/nested/example/SKILL.md", True),
        ("~/.pi/agent/skills/flat-skill.md", True),
        ("~/.agents/skills/flat-skill.md", True),
        ("~/.pi/agent/skills", True),
        ("~/.agents/skills", True),
        (".pi/skills/local/SKILL.md", False),
        (".agents/skills/local/SKILL.md", False),
        ("~/.pi/agent/skills-extra/SKILL.md", False),
        ("~/.pi/agent/skills/../untrusted.md", False),
    ],
    ids=[
        "pi-global-nested",
        "agents-global-nested",
        "pi-global-flat-file",
        "agents-global-flat-file",
        "pi-global-root",
        "agents-global-root",
        "project-pi-skills",
        "project-agents-skills",
        "prefix-collision",
        "traversal-escape",
    ],
)
def test_read_skills_are_limited_to_global_roots(
    path: str, allowed: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    home = tmp_path / "home"
    cwd = tmp_path / "project"
    result = decide(
        [
            {
                "mode": "tui",
                "toolName": "read",
                "input": {"path": path},
                "cwd": str(cwd),
                "home": str(home),
            }
        ]
    )[0]
    assert result["allowed"] is allowed


def test_pi_coding_agent_dir_override_applies_to_global_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    agent_dir = home / "custom-pi-agent"
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent_dir))

    results = decide(
        [
            {
                "mode": "tui",
                "toolName": "read",
                "input": {"path": str(agent_dir / "skills" / "nested" / "SKILL.md")},
                "cwd": str(tmp_path),
                "home": str(home),
            },
            {
                "mode": "tui",
                "toolName": "read",
                "input": {
                    "path": str(
                        home / ".pi" / "agent" / "skills" / "nested" / "SKILL.md"
                    )
                },
                "cwd": str(tmp_path),
                "home": str(home),
            },
        ]
    )

    assert [result["allowed"] for result in results] == [True, False]


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
def test_plan_phase_excludes_workers(mode: str, subagent: bool, expected: bool) -> None:
    """JSON/print workers and explicitly spawned children cannot enable the plan phase."""
    runner = """
import { pathToFileURL } from "node:url";
const module = await import(pathToFileURL(process.argv[1]).href);
console.log(JSON.stringify(module.isPlanPhaseActive(process.argv[2])));
"""
    mode_module = (
        MANAGED_ROOT / "dot_pi" / "agent" / "extensions" / "plan-mode" / "mode.mjs"
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
console.log(JSON.stringify(module.childEnvironment({ EXISTING: "value", PI_ROOT_PHASE: "plan" })));
"""
    child_env_module = (
        MANAGED_ROOT / "dot_pi" / "agent" / "extensions" / "subagent" / "child-env.mjs"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", runner, str(child_env_module)],
        check=True,
        capture_output=True,
        text=True,
    )
    child_environment = json.loads(result.stdout)
    assert child_environment == {
        "EXISTING": "value",
        "PI_ROOT_PHASE": "plan",
        "PI_SUBAGENT": "1",
    }
    assert "PI_MODE" not in child_environment

    extension = (
        MANAGED_ROOT / "dot_pi" / "agent" / "extensions" / "subagent" / "index.ts"
    )
    source = extension.read_text()
    assert "execution, approval: lease" in source
    assert "approval: lease" in source
