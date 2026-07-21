"""Tests for .claude/hooks/commit_session_artifacts.py commit provenance.

The session-artifact hook creates durable commits autonomously. Its commit message
therefore has a strict, minimal trailer surface: only runtime provenance fields that
are sanctioned for agent records may be emitted.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / ".claude" / "hooks" / "commit_session_artifacts.py"

_spec = importlib.util.spec_from_file_location("commit_session_artifacts", HOOK)
assert _spec and _spec.loader
_module = importlib.util.module_from_spec(_spec)
sys.modules["commit_session_artifacts"] = _module
_spec.loader.exec_module(_module)


@pytest.mark.parametrize(
    ("changed", "session_id"),
    [
        pytest.param(["todo.txt"], "session-1", id="one-artifact"),
        pytest.param(["todo.txt", "done.txt"], "session-2", id="multiple-artifacts"),
    ],
)
def test_commit_message_uses_only_approved_provenance_fields(
    changed: list[str], session_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Autonomous commits retain only the approved runtime provenance fields."""
    monkeypatch.setenv("CLAUDE_MODEL", "test-model")

    message = _module.build_commit_message(changed, session_id)
    provenance_block = message.rsplit("\n\n", maxsplit=1)[-1]
    labels = [line.split(":", maxsplit=1)[0] for line in provenance_block.splitlines()]

    assert f"Files: {', '.join(changed)}" in message
    assert labels == ["Authored-By", "Model", "Session-ID", "Hostname"]
