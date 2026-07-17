"""End-to-end worker coverage for Pi's applied ``audit_metadata`` extension.

The extension's unit harness controls its registration surface and runtime inputs. This
slow smoke test instead starts the installed Pi CLI in the same child-mode environment
used by the subagent launcher. It deliberately loads no extension by path and supplies
the worker's actual allowlist: success proves the global extension survives Pi's child
tool filtering and returns a valid runtime-owned metadata block.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

PI = shutil.which("pi")
LIVE_AGENT_ROOT = Path.home() / ".pi" / "agent"
LIVE_EXTENSION = LIVE_AGENT_ROOT / "extensions" / "audit-metadata.ts"
WORKER_AGENT = LIVE_AGENT_ROOT / "agents" / "worker.md"
PROMPT = "Call the audit_metadata tool exactly once. Then respond only with the tool result, unchanged."

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        PI is None or not LIVE_EXTENSION.is_file(),
        reason="The applied Pi CLI audit_metadata extension is required for worker smoke coverage",
    ),
]


def _worker_tool_allowlist() -> str:
    """Return the applied worker's tools passed by the real subagent launcher."""
    match = re.search(r"^tools: (?P<tools>.+)$", WORKER_AGENT.read_text(), re.MULTILINE)
    assert match is not None, f"worker tools allowlist not found in {WORKER_AGENT}"
    return match["tools"]


def _worker_environment() -> dict[str, str]:
    """Mirror subagent child mode while retaining Pi's configured authentication."""
    environment = os.environ.copy()
    for key in (
        "PI_CODING_AGENT_DIR",
        "PI_CODING_AGENT_SESSION_DIR",
        "PI_SUBAGENT",
        "PI_SUBAGENT_EXECUTION",
    ):
        environment.pop(key, None)
    environment.update(
        {
            "PI_SUBAGENT": "1",
            "PI_SUBAGENT_EXECUTION": "worktree-write",
            "PI_OFFLINE": "1",
        }
    )
    return environment


def _json_events(stdout: str) -> list[dict[str, Any]]:
    """Decode Pi's JSONL event stream and fail loudly on non-protocol output."""
    return [json.loads(line) for line in stdout.splitlines() if line]


def _assert_valid_runtime_block(result: dict[str, Any]) -> None:
    """Validate the paste-ready tool result without depending on local identity values."""
    content = result["content"]
    assert len(content) == 1
    assert content[0]["type"] == "text"
    lines = content[0]["text"].splitlines()
    labels = ("Model", "Model-Provider", "Session-ID", "Hostname")
    assert len(lines) == len(labels) + 1
    assert not any("(source:" in line for line in lines), lines

    harness_prefix = "Agent-Harness: Pi "
    assert lines[0].startswith(harness_prefix)
    harness_version = lines[0].removeprefix(harness_prefix)
    assert harness_version.strip()
    assert not harness_version.lower().startswith("unknown")
    assert "\r" not in harness_version and "\n" not in harness_version

    for label, line in zip(labels, lines[1:]):
        prefix = f"{label}: "
        assert line.startswith(prefix)
        value = line.removeprefix(prefix)
        assert value.strip()
        assert not value.lower().startswith("unknown")
        assert "\r" not in value and "\n" not in value

    details = result["details"]
    assert tuple(details) == ("model", "modelProvider", "sessionId", "hostname")
    assert tuple(details.values()) == tuple(
        line.removeprefix(f"{label}: ") for label, line in zip(labels, lines[1:])
    )


def test_worker_allowlist_preserves_audit_metadata_tool() -> None:
    """The worker allowlist must retain the skill-mandated audit metadata tool."""
    assert PI is not None
    result = subprocess.run(
        [
            PI,
            "--mode",
            "json",
            "--no-session",
            "--tools",
            _worker_tool_allowlist(),
            "-p",
            PROMPT,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
        env=_worker_environment(),
    )
    assert result.returncode == 0, result.stderr

    events = _json_events(result.stdout)
    tool_events = [
        event
        for event in events
        if event.get("type") == "tool_execution_end"
        and event.get("toolName") == "audit_metadata"
    ]
    assert len(tool_events) == 1
    tool_event = tool_events[0]
    assert tool_event["isError"] is False
    _assert_valid_runtime_block(tool_event["result"])
