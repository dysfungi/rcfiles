"""Tests for dot_claude/hooks/executable_clear_plan_review_sentinel.py.

Subprocess-driven integration tests — the companion Stop hook is invoked as a
real process (via its uv shebang), with JSON on stdin and HOME pointed at a tmp
dir. It always exits 0; the observable effect is whether the session-scoped
sentinel file was removed.

Behaviors covered:
  - Matching-sid sentinel present → removed, exit 0
  - Sentinel absent → exit 0, no error (missing_ok)
  - Session-scoped: a different session's sentinel is left untouched
  - No session id (payload + env absent) → resolves the fallback name and removes it
  - Valid-but-non-object JSON (`[]`, `"foo"`, ...) → exit 0, nothing cleaned up
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
    REPO_ROOT
    / "home"
    / "dot_claude"
    / "hooks"
    / "executable_clear_plan_review_sentinel.py"
)

assert HOOK.exists(), f"hook not found at {HOOK}"

_SID = "test-session"
# Must mirror _NO_SESSION in the hook (and the gate hook it resets).
_NO_SESSION = "no-session"


def _run_hook(payload: dict, home: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the hook with the given JSON payload and a controlled HOME."""
    return _run_hook_raw(json.dumps(payload), home=home)


def _run_hook_raw(stdin: str, home: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the hook with a raw stdin string (for non-object-JSON cases)."""
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(
        [str(HOOK)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
    )


def _sentinel(home: Path, sid: str = _SID) -> Path:
    return home / ".claude" / f"exit-plan-review-fired.{sid}"


def _make_sentinel(home: Path, sid: str = _SID) -> Path:
    sentinel = _sentinel(home, sid)
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()
    return sentinel


def test_removes_matching_sentinel(tmp_path: Path) -> None:
    """A sentinel for the payload's session id is removed → exit 0."""
    sentinel = _make_sentinel(tmp_path)
    result = _run_hook({"session_id": _SID}, home=tmp_path)
    assert result.returncode == 0, (
        f"Expected exit 0, got {result.returncode}.\nstderr: {result.stderr!r}"
    )
    assert not sentinel.exists(), "Expected the matching sentinel to be removed"


def test_absent_sentinel_is_noop(tmp_path: Path) -> None:
    """No sentinel present → exit 0 with no error (missing_ok)."""
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    result = _run_hook({"session_id": _SID}, home=tmp_path)
    assert result.returncode == 0, (
        f"Expected exit 0 when sentinel absent, got {result.returncode}.\n"
        f"stderr: {result.stderr!r}"
    )


def test_leaves_other_sessions_sentinel(tmp_path: Path) -> None:
    """Only the current session's sentinel is removed; siblings are untouched."""
    mine = _make_sentinel(tmp_path, sid=_SID)
    other = _make_sentinel(tmp_path, sid="other-session")

    result = _run_hook({"session_id": _SID}, home=tmp_path)
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}"
    assert not mine.exists(), "Current session's sentinel should be removed"
    assert other.exists(), "A different session's sentinel must NOT be removed"


def test_no_session_id_removes_fallback_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no session id anywhere, the fallback-named sentinel is resolved and removed."""
    # Ensure the subprocess env does NOT inherit a session id from the test runner.
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    sentinel = _make_sentinel(tmp_path, sid=_NO_SESSION)

    result = _run_hook({}, home=tmp_path)
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}"
    assert not sentinel.exists(), (
        "Expected the fallback sentinel (exit-plan-review-fired.no-session) removed"
    )


_NON_OBJECT_JSON = ["[]", '"foo"', "42", "true", "null"]


@pytest.mark.parametrize(
    "stdin", _NON_OBJECT_JSON, ids=["array", "string", "number", "bool", "null"]
)
def test_non_object_json_is_noop(stdin: str, tmp_path: Path) -> None:
    """Valid-but-non-object JSON has no `.get` → exit 0, nothing cleaned up."""
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    result = _run_hook_raw(stdin, home=tmp_path)
    assert result.returncode == 0, (
        f"Expected exit 0 for non-object JSON {stdin!r}, got {result.returncode}.\n"
        f"stderr: {result.stderr!r}"
    )
