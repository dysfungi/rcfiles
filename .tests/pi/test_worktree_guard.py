"""Runtime regression tests for Pi's root and child worktree mutation boundary."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from _test_env import _clean_env

REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGED_ROOT = REPO_ROOT / "home"
HARNESS = REPO_ROOT / ".tests" / "pi" / "worktree_guard_runtime_harness.mjs"
GUARD = MANAGED_ROOT / "dot_pi" / "agent" / "extensions" / "worktree-guard.ts"
REGISTRY = (
    MANAGED_ROOT / "dot_pi" / "agent" / "extensions" / "worktree-approval-registry.mjs"
)
PI = shutil.which("pi")
NODE = shutil.which("node")

pytestmark = [
    pytest.mark.skipif(
        PI is None or NODE is None,
        reason="Pi CLI and Node.js are required for worktree-guard runtime coverage",
    ),
    pytest.mark.skip(reason="60s hang + leaks child processes; see todo.txt"),
]


def test_root_and_child_worktree_guard_runtime() -> None:
    """Exercise real extension handlers against linked Git worktrees."""
    assert PI is not None
    assert NODE is not None
    package_dir = Path(PI).resolve().parent.parent
    result = subprocess.run(
        [NODE, str(HARNESS), str(GUARD), str(REGISTRY), str(package_dir)],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
        env=_clean_env(),
    )
    assert result.stdout == "ok\n"
