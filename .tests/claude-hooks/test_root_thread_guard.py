"""Tests for dot_claude/hooks/executable_root_thread_guard.py.

Subprocess-driven integration tests — the hook is invoked as a real process
(via its uv shebang), with JSON fed on stdin. This tests the full execution
path, including shebang resolution and stdin parsing.

Truth table: each case asserts whether the hook exits 0 (allow) or 2 (block).
Exit code 2 is the Claude Code hooks convention for "hard deny".
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# Source path in the repo; applied to ~/.claude/hooks/ by chezmoi, stripping
# the "executable_" prefix. Tests invoke the source directly.
HOOK = REPO_ROOT / "dot_claude" / "hooks" / "executable_root_thread_guard.py"

assert HOOK.exists(), f"hook not found at {HOOK}"


def _run_hook(payload: dict, home: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the hook with the given JSON payload and a controlled HOME."""
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )


def _root_payload(tool: str, **extra) -> dict:
    """Payload that looks like a root-thread call (no agent_id)."""
    return {"tool_name": tool, "session_id": "test-session", **extra}


def _subagent_payload(tool: str, **extra) -> dict:
    """Payload that looks like a subagent call (agent_id present)."""
    return {
        "tool_name": tool,
        "session_id": "test-session",
        "agent_id": "subagent-abc123",
        "agent_type": "scout",
        **extra,
    }


# ---------------------------------------------------------------------------
# Root thread: blocked tools (no agent_id) → exit 2
# ---------------------------------------------------------------------------

_BLOCKED_IN_ROOT = [
    ("Read", "file reader"),
    ("Grep", "pattern search"),
    ("Glob", "file glob"),
    ("Bash", "shell command"),
    ("WebFetch", "web content fetch"),
    ("WebSearch", "web search"),
]


@pytest.mark.parametrize(
    "tool,label", _BLOCKED_IN_ROOT, ids=[x[0] for x in _BLOCKED_IN_ROOT]
)
def test_root_thread_blocked(tool: str, label: str, tmp_path: Path) -> None:
    """Blocked tools in the root thread exit 2."""
    result = _run_hook(_root_payload(tool), home=tmp_path)
    assert result.returncode == 2, (
        f"Expected exit 2 for {tool} in root thread, got {result.returncode}.\n"
        f"stderr: {result.stderr!r}"
    )
    assert tool in result.stderr, f"Expected tool name {tool!r} in deny message"
    assert "root-guard-exempt" in result.stderr, (
        "Expected sentinel hint in deny message"
    )


# ---------------------------------------------------------------------------
# Subagent context: same blocked tools are allowed (agent_id present) → exit 0
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool,label", _BLOCKED_IN_ROOT, ids=[x[0] for x in _BLOCKED_IN_ROOT]
)
def test_subagent_allowed(tool: str, label: str, tmp_path: Path) -> None:
    """Same tools are allowed when agent_id is present (subagent context)."""
    result = _run_hook(_subagent_payload(tool), home=tmp_path)
    assert result.returncode == 0, (
        f"Expected exit 0 for {tool} in subagent, got {result.returncode}.\n"
        f"stderr: {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Always-allowed tools in root thread → exit 0
# ---------------------------------------------------------------------------

_ALWAYS_ALLOWED = [
    "Agent",
    "Task",
    "Write",
    "Edit",
    "NotebookEdit",
    "TodoWrite",
    "AskUserQuestion",
    "ExitPlanMode",
    "Skill",
    "mcp__notion__notion-fetch",
    "mcp__slack__post_message",
]


@pytest.mark.parametrize("tool", _ALWAYS_ALLOWED)
def test_always_allowed_in_root(tool: str, tmp_path: Path) -> None:
    """Non-blocked tools in root thread are always allowed."""
    result = _run_hook(_root_payload(tool), home=tmp_path)
    assert result.returncode == 0, (
        f"Expected exit 0 for {tool} in root thread, got {result.returncode}.\n"
        f"stderr: {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Sentinel file exemption → blocked tools allowed in root thread
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool,label", _BLOCKED_IN_ROOT, ids=[x[0] for x in _BLOCKED_IN_ROOT]
)
def test_sentinel_file_exempts_root(tool: str, label: str, tmp_path: Path) -> None:
    """When ~/.claude/root-guard-exempt exists, blocked tools are allowed."""
    sentinel = tmp_path / ".claude" / "root-guard-exempt"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()

    result = _run_hook(_root_payload(tool), home=tmp_path)
    assert result.returncode == 0, (
        f"Expected exit 0 for {tool} with sentinel file, got {result.returncode}.\n"
        f"stderr: {result.stderr!r}"
    )


def test_sentinel_file_absence_still_blocks(tmp_path: Path) -> None:
    """Without sentinel, blocking is active (sanity check)."""
    # Ensure .claude dir exists but sentinel is absent
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    result = _run_hook(_root_payload("Bash"), home=tmp_path)
    assert result.returncode == 2
