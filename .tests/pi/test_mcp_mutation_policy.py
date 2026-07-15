"""Behavioral coverage for Pi's best-effort MCP mutation classifier."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGED_ROOT = REPO_ROOT / "home"
HARNESS = Path(__file__).with_name("mcp_mutation_policy_harness.mjs")
POLICY = MANAGED_ROOT / "dot_pi" / "agent" / "extensions" / "mcp-mutation-policy.mjs"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    NODE is None, reason="Node.js is required for MCP policy coverage"
)


def test_mcp_mutation_policy() -> None:
    """Keep gateway dispatch precedence and verb-token matching explicit."""
    assert NODE is not None
    result = subprocess.run(
        [NODE, str(HARNESS), str(POLICY)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.stdout == "mcp mutation policy harness: ok\n"
