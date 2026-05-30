"""Shared fixtures for chezmoi dotfiles tests.

GIT ISOLATION NOTE
    Several test helpers run `git init` / `git commit` to build throwaway repos.
    When tests run under pre-commit, GIT_DIR / GIT_INDEX_FILE / etc. are leaked
    into subprocess env, which redirects those git calls into the REAL chezmoi
    repo and can corrupt its config (e.g. core.bare=true).

    All subprocess calls that invoke git MUST pass env=_clean_env() (or a superset
    that still strips GIT_*) to prevent this.  The assert_real_repo_unaffected
    session fixture is the safety net: it asserts the real repo's core.bare and
    HEAD are unchanged after every test session.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_REAL_GIT_DIR = REPO_ROOT / ".git"


def _clean_env() -> dict[str, str]:
    """Return os.environ with GIT_* vars stripped.

    Pre-commit leaks GIT_DIR / GIT_INDEX_FILE / etc. into subprocess env;
    stripping them ensures git calls hit the intended repo (tmp or cwd),
    not the real chezmoi repo.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


@pytest.fixture(scope="session", autouse=True)
def assert_real_repo_unaffected() -> Any:
    """Guard: assert the real chezmoi repo is not corrupted by any test.

    Records core.bare and HEAD sha before all tests and asserts both are
    unchanged after the session.  A failure here means GIT isolation broke
    and a test touched the real repo — find and fix the offending subprocess
    call by adding env=_clean_env() and an appropriate cwd.
    """

    def _git(*args: str) -> str:
        return subprocess.run(
            ["git", "--git-dir", str(_REAL_GIT_DIR), *args],
            capture_output=True,
            text=True,
        ).stdout.strip()

    before_bare = _git("config", "--get", "core.bare") or "false"
    before_head = _git("rev-parse", "HEAD")
    yield
    after_bare = _git("config", "--get", "core.bare") or "false"
    after_head = _git("rev-parse", "HEAD")
    assert after_bare == before_bare, (
        f"real repo core.bare changed during tests: {before_bare!r} → {after_bare!r}\n"
        "A test leaked GIT_DIR into a subprocess — add env=_clean_env() to the call."
    )
    assert after_head == before_head, (
        f"real repo HEAD changed during tests: {before_head!r} → {after_head!r}\n"
        "A test committed to the real repo — add env=_clean_env() and cwd= to the call."
    )


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a throwaway git repo with an initial commit.

    Returns the repo root path. Useful for integration tests that need
    is_main_worktree(), worktree creation, or branch operations.
    """
    clean = _clean_env()
    subprocess.run(
        ["git", "init", str(tmp_path)], check=True, capture_output=True, env=clean
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        env={
            **clean,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
            "HOME": str(tmp_path),
        },
    )
    return tmp_path
