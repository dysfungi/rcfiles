"""Applied-agent contract for Pi's universally available audit metadata tool.

The worker smoke test exercises Pi's child-mode tool filtering end to end. This
fast check covers the separate regression risk: a role's managed allowlist can
silently omit the read-only provenance tool.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

LIVE_AGENT_ROOT = Path.home() / ".pi" / "agent" / "agents"

# audit_metadata is a read-only provenance tool intentionally granted to every
# subagent type; this guards against an allowlist edit silently revoking it.
AGENT_CASES = [
    pytest.param("worker", id="worker"),
    pytest.param("scout", id="scout"),
    pytest.param("reviewer", id="reviewer"),
    pytest.param("planner", id="planner"),
]


@pytest.mark.parametrize("agent_name", AGENT_CASES)
def test_agent_allowlist_includes_audit_metadata(agent_name: str) -> None:
    """Each applied subagent definition retains audit metadata access."""
    agent_path = LIVE_AGENT_ROOT / f"{agent_name}.md"
    assert agent_path.is_file(), f"applied agent definition not found: {agent_path}"
    match = re.search(r"^tools: (?P<tools>.+)$", agent_path.read_text(), re.MULTILINE)
    assert match is not None, f"tools allowlist not found in {agent_path}"
    assert "audit_metadata" in match["tools"].split(", ")
