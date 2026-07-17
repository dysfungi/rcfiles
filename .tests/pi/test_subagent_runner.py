"""Behavioral tests for Pi subagent execution-class launch policy."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

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
    pytest.mark.skip(reason="60s hang + leaks child processes; see todo.txt"),
]


def test_subagent_execution_preflight_and_leases() -> None:
    """Exercise real launcher preflight and child environment handling."""
    assert PI is not None
    assert NODE is not None
    package_dir = Path(PI).resolve().parent.parent
    result = subprocess.run(
        [NODE, HARNESS, EXTENSION, GUARD, REGISTRY, package_dir],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env={
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("GIT_", "PI_SUBAGENT", "PI_WORKTREE"))
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "subagent runner runtime harness: ok\n"
