"""Runtime regression tests for Pi's root and child worktree mutation boundary."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from _test_env import _clean_env, _mise_pi_runtime_paths, _run_process_group

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
]


def test_root_and_child_worktree_guard_runtime() -> None:
    """Exercise real extension handlers against linked Git worktrees."""
    assert PI is not None
    assert NODE is not None
    environment = _clean_env()
    package_dir, node = _mise_pi_runtime_paths(REPO_ROOT, environment)
    result = _run_process_group(
        [str(node), str(HARNESS), str(GUARD), str(REGISTRY), str(package_dir)],
        cwd=REPO_ROOT,
        environment=environment,
        timeout_seconds=60,
        phase="worktree guard runtime harness",
    )
    assert result.stdout == "ok\n"
