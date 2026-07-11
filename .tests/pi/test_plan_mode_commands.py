"""Behavioral coverage for Pi plan-mode command handlers.

The Node harness loads the real TypeScript extension through Pi's bundled Jiti
loader, captures its public ``ExtensionAPI`` registrations, and invokes the
handlers with controlled extension contexts. This covers command behavior
without starting an LLM turn or coupling tests to source-text implementation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EXTENSION = REPO_ROOT / "dot_pi" / "agent" / "extensions" / "plan-mode" / "index.ts"
HARNESS = Path(__file__).with_name("plan_mode_runtime_harness.mjs")
PI = shutil.which("pi")
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    PI is None or NODE is None,
    reason="Pi CLI and Node.js are required for plan-mode runtime coverage",
)


def test_plan_mode_command_handlers() -> None:
    """Exercise registered command and context handlers without an LLM run."""
    assert PI is not None
    assert NODE is not None
    package_dir = Path(PI).resolve().parent.parent

    result = subprocess.run(
        [NODE, HARNESS, EXTENSION, package_dir],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env={
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_") and key != "PI_SUBAGENT"
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "plan-mode runtime handler harness: ok\n"
