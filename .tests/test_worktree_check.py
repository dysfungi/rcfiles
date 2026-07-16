"""Exercise the real Claude Write/Edit worktree guard exemptions."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = "/repo"
REPO_PREFIX = REPO_ROOT + "/"
HOOK = Path(__file__).resolve().parents[1] / ".claude/hooks/worktree_check.py"
_spec = importlib.util.spec_from_file_location("worktree_check", HOOK)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["worktree_check"] = _mod
_spec.loader.exec_module(_mod)


@pytest.fixture
def invoke_pre_tool_use(monkeypatch: pytest.MonkeyPatch):
    """Invoke the hook with a fixed Git root and a synthetic Claude payload."""
    monkeypatch.setattr(_mod, "is_exempt", lambda *_: False)
    monkeypatch.setattr(
        _mod.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=f"{REPO_ROOT}\n"),
    )

    def invoke(file_path: str) -> None:
        payload = {"tool_input": {"file_path": file_path}}
        monkeypatch.setattr(_mod.sys, "stdin", io.StringIO(json.dumps(payload)))
        _mod.handle_pre_tool_use(REPO_ROOT)

    return invoke


_EXEMPT_PATHS = [
    (REPO_PREFIX + ".claude/settings.json", ".claude/ files are exempt"),
    (REPO_PREFIX + ".claude/hooks/some_hook.py", ".claude/hooks/ are exempt"),
    (REPO_PREFIX + "todo.txt", "todo.txt at repo root is exempt"),
    (REPO_PREFIX + "done.txt", "done.txt at repo root is exempt"),
    ("/tmp/anything.py", "files outside repo are exempt"),
    ("/other/repo/todo.txt", "todo.txt in different repo is exempt"),
]


@pytest.mark.parametrize(
    ("path", "desc"), _EXEMPT_PATHS, ids=[case[1] for case in _EXEMPT_PATHS]
)
def test_exempt_paths(invoke_pre_tool_use, path: str, desc: str) -> None:
    invoke_pre_tool_use(path)


_BLOCKED_PATHS = [
    (REPO_PREFIX + "some_file.py", "regular repo file"),
    (REPO_PREFIX + "subdir/todo.txt", "todo.txt in subdirectory"),
    (REPO_PREFIX + "subdir/done.txt", "done.txt in subdirectory"),
    (REPO_PREFIX + ".github/workflows/cicd.yaml", "CI workflow file"),
    (REPO_PREFIX + "CLAUDE.md", "CLAUDE.md (not in .claude/)"),
]


@pytest.mark.parametrize(
    ("path", "desc"), _BLOCKED_PATHS, ids=[case[1] for case in _BLOCKED_PATHS]
)
def test_repo_paths_are_blocked(invoke_pre_tool_use, path: str, desc: str) -> None:
    with pytest.raises(SystemExit, match="2"):
        invoke_pre_tool_use(path)


def test_payload_session_exemption_overrides_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claude's payload session ID selects the matching per-session exemption."""
    exempt_dir = tmp_path / ".claude"
    exempt_dir.mkdir()
    (exempt_dir / "worktree-exempt.payload-session").touch()
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "environment-session")

    assert _mod.is_exempt(str(tmp_path), {"session_id": "payload-session"})


def test_global_exemption_applies_without_session_id(tmp_path: Path) -> None:
    """The human-only global exemption remains available outside a Claude session."""
    exempt_dir = tmp_path / ".claude"
    exempt_dir.mkdir()
    (exempt_dir / "worktree-exempt").touch()

    assert _mod.is_exempt(str(tmp_path))
