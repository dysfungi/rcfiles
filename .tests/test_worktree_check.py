"""Tests for .claude/hooks/worktree_check.py — Write/Edit worktree guard.

Validates the path-exemption logic that decides which files can be written
on the main worktree without entering a linked worktree.
"""

from __future__ import annotations

import pytest


REPO_ROOT = "/repo"
REPO_PREFIX = REPO_ROOT + "/"


def is_exempt_path(file_path: str) -> bool:
    """Replicate the exemption logic from worktree_check.py handle_pre_tool_use."""
    if not file_path.startswith(REPO_PREFIX):
        return True
    if file_path.startswith(REPO_PREFIX + ".claude/"):
        return True
    basename = file_path[len(REPO_PREFIX) :]
    if basename in ("todo.txt", "done.txt"):
        return True
    return False


_EXEMPT = [
    (REPO_PREFIX + ".claude/settings.json", ".claude/ files are exempt"),
    (REPO_PREFIX + ".claude/hooks/some_hook.py", ".claude/hooks/ are exempt"),
    (REPO_PREFIX + "todo.txt", "todo.txt at repo root is exempt"),
    (REPO_PREFIX + "done.txt", "done.txt at repo root is exempt"),
    ("/tmp/anything.py", "files outside repo are exempt"),
    ("/other/repo/todo.txt", "todo.txt in different repo is exempt"),
]


@pytest.mark.parametrize(("path", "desc"), _EXEMPT, ids=[e[1] for e in _EXEMPT])
def test_exempt_paths(path: str, desc: str) -> None:
    assert is_exempt_path(path), f"should be exempt: {desc}"


_BLOCKED = [
    (REPO_PREFIX + "some_file.py", "regular repo file"),
    (REPO_PREFIX + "subdir/todo.txt", "todo.txt in subdirectory"),
    (REPO_PREFIX + "subdir/done.txt", "done.txt in subdirectory"),
    (REPO_PREFIX + ".github/workflows/cicd.yaml", "CI workflow file"),
    (REPO_PREFIX + "CLAUDE.md", "CLAUDE.md (not in .claude/)"),
]


@pytest.mark.parametrize(("path", "desc"), _BLOCKED, ids=[b[1] for b in _BLOCKED])
def test_blocked_paths(path: str, desc: str) -> None:
    assert not is_exempt_path(path), f"should be blocked: {desc}"
