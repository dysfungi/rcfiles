"""Tests for dynamic TODO_DIR discovery in dot_todo/config.

WHY this test exists: dot_todo/config (→ ~/.todo/config) computes TODO_DIR at
source-time via `git rev-parse --show-toplevel`, scoping bare `todo.sh` commands
to whichever git repo/worktree you're in. These tests verify the four opt-in
cases using real git repos and real filesystem — no mocks.

The discovery mechanism is tested by sourcing the config in a bash subprocess
with CWD set to the target directory, which is exactly how todo.sh invokes it.

GIT ISOLATION
    All subprocess calls that invoke git pass env=_clean_env() to strip any
    GIT_DIR / GIT_INDEX_FILE / etc. leaked by pre-commit; without this, git
    calls hit the real chezmoi repo and can corrupt its config (core.bare=true).
    The session-wide assert_real_repo_unaffected fixture in conftest.py is the
    safety net that catches regressions in this layer.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

# Path to the config file under test.
_CONFIG = Path(__file__).resolve().parents[1] / "dot_todo" / "config"


def _clean_env() -> dict[str, str]:
    """Return os.environ with GIT_* vars stripped.

    Pre-commit leaks GIT_DIR / GIT_INDEX_FILE / etc. into subprocess env;
    stripping them ensures git calls hit the intended tmp repo, not the real
    chezmoi repo.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _source_and_get_todo_dir(cwd: Path) -> str:
    """Source dot_todo/config in bash from cwd and return the value of TODO_DIR."""
    result = subprocess.run(
        ["bash", "-c", f'. "{_CONFIG}" && printf "%s" "${{TODO_DIR:-}}"'],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    return result.stdout


# ---------------------------------------------------------------------------
# Table-driven cases
# ---------------------------------------------------------------------------

# Each case: (description, setup_fn, expected_fn)
# setup_fn: (tmp_path) -> cwd_path
# expected_fn: (cwd_path) -> expected TODO_DIR value (empty string == unset)
_CASES: list[tuple[str, Callable[[Path], Path], Callable[[Path], str]]] = [
    (
        "repo opted in — root todo.txt present",
        lambda p: _make_opted_in_repo(p),
        lambda cwd: _git_toplevel(cwd),
    ),
    (
        "from subdirectory — discovery still finds repo root",
        lambda p: _make_opted_in_subdir(p),
        lambda cwd: _git_toplevel(cwd),
    ),
    (
        "repo without todo.txt — not opted in, TODO_DIR unset",
        lambda p: _make_bare_repo(p),
        lambda _: "",
    ),
    (
        "outside any git repo — TODO_DIR unset",
        lambda p: _make_plain_dir(p),
        lambda _: "",
    ),
]


@pytest.mark.parametrize(
    ("desc", "make_cwd", "expected"),
    _CASES,
    ids=["opted-in", "from-subdir", "no-todo-txt", "not-a-repo"],
)
def test_todo_dir_discovery(
    tmp_path: Path,
    desc: str,
    make_cwd: Callable[[Path], Path],
    expected: Callable[[Path], str],
) -> None:
    cwd = make_cwd(tmp_path)
    actual = _source_and_get_todo_dir(cwd)
    want = expected(cwd)
    assert actual == want, f"[{desc}] expected TODO_DIR={want!r}, got {actual!r}"


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------


def _make_opted_in_repo(base: Path) -> Path:
    """Create a git repo with a root todo.txt (opted in). Returns repo root."""
    repo = base / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", str(repo)], check=True, capture_output=True, env=_clean_env()
    )
    _git_commit_empty(repo)
    (repo / "todo.txt").touch()
    return repo


def _make_opted_in_subdir(base: Path) -> Path:
    """Create an opted-in repo with a subdirectory; return the subdir as cwd."""
    repo = _make_opted_in_repo(base)
    subdir = repo / "subdir"
    subdir.mkdir()
    return subdir


def _make_bare_repo(base: Path) -> Path:
    """Create a git repo with NO todo.txt. Returns repo root."""
    repo = base / "bare-repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", str(repo)], check=True, capture_output=True, env=_clean_env()
    )
    _git_commit_empty(repo)
    return repo


def _make_plain_dir(base: Path) -> Path:
    """Create a plain directory — no git at all. Returns it."""
    plain = base / "plain"
    plain.mkdir()
    return plain


def _git_commit_empty(repo: Path) -> None:
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        env={
            **_clean_env(),
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
            "HOME": str(repo),
        },
    )


def _git_toplevel(path: Path) -> str:
    """Resolve git root via git itself — handles macOS /tmp → /private/tmp symlinks."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
        env=_clean_env(),
    )
    return result.stdout.strip()
