"""Behavioral tests for Pi subagent execution-class launch policy."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from _test_env import _mise_pi_runtime_paths, _run_process_group

REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGED_ROOT = REPO_ROOT / "home"
EXTENSION = MANAGED_ROOT / "dot_pi" / "agent" / "extensions" / "subagent" / "index.ts"
GUARD = MANAGED_ROOT / "dot_pi" / "agent" / "extensions" / "worktree-guard.ts"
REGISTRY = (
    MANAGED_ROOT / "dot_pi" / "agent" / "extensions" / "worktree-approval-registry.mjs"
)
HARNESS = Path(__file__).with_name("subagent_runner_runtime_harness.mjs")
PI = shutil.which("pi")
NODE = shutil.which("node")

pytestmark = [
    pytest.mark.skipif(
        PI is None or NODE is None,
        reason="Pi CLI and Node.js are required for subagent runner runtime coverage",
    ),
    pytest.mark.skipif(
        os.name == "nt",
        reason="subagent runner runtime coverage requires POSIX process groups",
    ),
]


def test_subagent_execution_preflight_and_leases() -> None:
    """Exercise real launcher preflight and child environment handling."""
    assert PI is not None
    assert NODE is not None
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GIT_", "PI_SUBAGENT", "PI_WORKTREE"))
    }
    package_dir, node = _mise_pi_runtime_paths(REPO_ROOT, environment)
    result = _run_process_group(
        [
            str(node),
            str(HARNESS),
            str(EXTENSION),
            str(GUARD),
            str(REGISTRY),
            str(package_dir),
        ],
        cwd=REPO_ROOT,
        environment=environment,
        timeout_seconds=60,
        phase="subagent runner runtime harness",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "subagent runner runtime harness: ok\n"
