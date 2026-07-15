"""Tests for dot_claude/hooks/executable_exit_plan_review_gate.py.

Subprocess-driven integration tests — the hook is invoked as a real process
(via its uv shebang), with JSON fed on stdin and HOME pointed at a tmp dir so
the per-session sentinel is created under a controlled path. This exercises the
full execution path, including shebang resolution and stdin parsing.

Truth table: each case asserts whether the hook exits 0 (allow) or 2 (block).
Exit code 2 is the Claude Code hooks convention for "hard deny"; its stderr is
returned to the model as the reminder payload.

Cadence is per-TURN, not per-session: the sentinel only suppresses the immediate
within-turn re-call (after the self-review runs). The companion
clear_plan_review_sentinel Stop hook deletes it at the turn boundary, so a fresh
turn re-gates — modelled here by deleting the sentinel between calls.

Behaviors covered:
  - First ExitPlanMode with no sentinel → exit 2 + reminder in stderr + sentinel created
  - Sentinel already present → exit 0 (no re-block within the same turn)
  - Turn boundary: block, sentinel cleared, next call blocks again
  - No session id (payload + env both absent) → fallback-named sentinel, exit 2
  - Empty / invalid stdin → exit 0 (nothing to gate)
  - Valid-but-non-object JSON (`[]`, `"foo"`, ...) → exit 0, no block, no sentinel
  - Non-ExitPlanMode tool names → exit 0 and no sentinel created
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# Source path in the repo; applied to ~/.claude/hooks/ by chezmoi, stripping the
# "executable_" prefix. Tests invoke the source directly.
HOOK = (
    REPO_ROOT / "home" / "dot_claude" / "hooks" / "executable_exit_plan_review_gate.py"
)

assert HOOK.exists(), f"hook not found at {HOOK}"

_SID = "test-session"
# Must mirror _NO_SESSION in the hook (and its companion reset hook).
_NO_SESSION = "no-session"


def _run_hook(payload: dict, home: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the hook with the given JSON payload and a controlled HOME."""
    return _run_hook_raw(json.dumps(payload), home=home)


def _run_hook_raw(stdin: str, home: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the hook with a raw stdin string (for empty/invalid-JSON cases)."""
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(
        [str(HOOK)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
    )


def _payload(tool: str, sid: str = _SID) -> dict:
    """A PreToolUse payload carrying a session id for the per-session sentinel."""
    return {"tool_name": tool, "session_id": sid}


def _sentinel(home: Path, sid: str = _SID) -> Path:
    return home / ".claude" / f"exit-plan-review-fired.{sid}"


def test_first_exit_plan_blocks(tmp_path: Path) -> None:
    """First ExitPlanMode with no sentinel → exit 2, reminder in stderr, sentinel created."""
    result = _run_hook(_payload("ExitPlanMode"), home=tmp_path)
    assert result.returncode == 2, (
        f"Expected exit 2 on first ExitPlanMode, got {result.returncode}.\n"
        f"stderr: {result.stderr!r}"
    )
    assert "my-code-review" in result.stderr, (
        "Expected the self-review reminder (mentioning my-code-review) in stderr"
    )
    assert _sentinel(tmp_path).exists(), (
        "Expected the per-session sentinel to be created"
    )


def test_sentinel_precreated_allows(tmp_path: Path) -> None:
    """A pre-existing sentinel means the reminder already fired this turn → exit 0."""
    sentinel = _sentinel(tmp_path)
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()

    result = _run_hook(_payload("ExitPlanMode"), home=tmp_path)
    assert result.returncode == 0, (
        f"Expected exit 0 with sentinel pre-created, got {result.returncode}.\n"
        f"stderr: {result.stderr!r}"
    )


def test_does_not_reblock_while_sentinel_present(tmp_path: Path) -> None:
    """First call blocks and creates the sentinel; an identical second call passes.

    This is the within-turn de-dup: once reminded, the immediate re-call (after the
    self-review) must pass through so the plan can be presented in the same turn.
    """
    first = _run_hook(_payload("ExitPlanMode"), home=tmp_path)
    assert first.returncode == 2, f"First call should block, got {first.returncode}"

    second = _run_hook(_payload("ExitPlanMode"), home=tmp_path)
    assert second.returncode == 0, (
        f"Second identical call should pass (no re-block within a turn), "
        f"got {second.returncode}.\nstderr: {second.stderr!r}"
    )


def test_reblocks_after_turn_boundary(tmp_path: Path) -> None:
    """Clearing the sentinel (as the Stop hook does) re-gates the next turn's plan."""
    first = _run_hook(_payload("ExitPlanMode"), home=tmp_path)
    assert first.returncode == 2, f"First call should block, got {first.returncode}"
    assert _sentinel(tmp_path).exists(), "Sentinel should exist after first block"

    # Simulate the turn boundary: the companion Stop hook removes the sentinel.
    _sentinel(tmp_path).unlink()

    third = _run_hook(_payload("ExitPlanMode"), home=tmp_path)
    assert third.returncode == 2, (
        f"After the sentinel is cleared, the next plan must re-gate (exit 2), "
        f"got {third.returncode}.\nstderr: {third.stderr!r}"
    )


def test_no_session_id_uses_fallback_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no session_id in payload and no env var, the fallback name is used → exit 2."""
    # Ensure the subprocess env does NOT inherit a session id from the test runner:
    # _run_hook copies os.environ after this delenv, so the var is genuinely absent.
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

    result = _run_hook({"tool_name": "ExitPlanMode"}, home=tmp_path)
    assert result.returncode == 2, (
        f"Expected exit 2 with no session id, got {result.returncode}.\n"
        f"stderr: {result.stderr!r}"
    )
    assert _sentinel(tmp_path, sid=_NO_SESSION).exists(), (
        "Expected the fallback-named sentinel (exit-plan-review-fired.no-session)"
    )


_INVALID_STDIN = ["", "   ", "not json", "{unterminated"]


@pytest.mark.parametrize(
    "stdin", _INVALID_STDIN, ids=["empty", "blank", "text", "broken-json"]
)
def test_empty_or_invalid_stdin_allows(stdin: str, tmp_path: Path) -> None:
    """Empty/invalid stdin is tolerated → exit 0, nothing to gate."""
    result = _run_hook_raw(stdin, home=tmp_path)
    assert result.returncode == 0, (
        f"Expected exit 0 for invalid stdin {stdin!r}, got {result.returncode}.\n"
        f"stderr: {result.stderr!r}"
    )


_NON_OBJECT_JSON = ["[]", '"foo"', "42", "true", "null"]


@pytest.mark.parametrize(
    "stdin", _NON_OBJECT_JSON, ids=["array", "string", "number", "bool", "null"]
)
def test_non_object_json_allows(stdin: str, tmp_path: Path) -> None:
    """Valid-but-non-object JSON has no `.get` → exit 0, no block, no sentinel."""
    result = _run_hook_raw(stdin, home=tmp_path)
    assert result.returncode == 0, (
        f"Expected exit 0 for non-object JSON {stdin!r}, got {result.returncode}.\n"
        f"stderr: {result.stderr!r}"
    )
    assert not _sentinel(tmp_path).exists(), (
        f"No sentinel should be created for non-object JSON {stdin!r}"
    )


_NON_GATED_TOOLS = ["Write", "Read", "Bash", "Edit"]


@pytest.mark.parametrize("tool", _NON_GATED_TOOLS)
def test_non_exit_plan_tool_allowed(tool: str, tmp_path: Path) -> None:
    """Any tool other than ExitPlanMode is allowed (exit 0) and creates no sentinel."""
    result = _run_hook(_payload(tool), home=tmp_path)
    assert result.returncode == 0, (
        f"Expected exit 0 for {tool}, got {result.returncode}.\n"
        f"stderr: {result.stderr!r}"
    )
    assert not _sentinel(tmp_path).exists(), (
        f"No sentinel should be created for non-gated tool {tool}"
    )
