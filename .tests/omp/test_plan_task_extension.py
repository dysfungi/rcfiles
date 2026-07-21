"""Exercise the managed OMP plan-task extension through Bun.

The TypeScript harness registers the real extension against controlled RPC streams,
then proves its worker protocol, process cleanup, and tool contract without a model
request. Pytest owns only environment-neutral process invocation and diagnostics.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).with_name("plan_task_runtime_harness.ts")


def test_plan_task_extension_runtime_contract() -> None:
    """The plan-mode worker preserves the RPC protocol and reaps its process tree."""
    result = subprocess.run(
        ["mise", "x", "--", "bun", str(HARNESS)],
        capture_output=True,
        cwd=REPO_ROOT,
        text=True,
    )
    assert result.returncode == 0, result.stderr
