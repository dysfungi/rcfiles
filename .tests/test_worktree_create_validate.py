"""Tests for .claude/hooks/worktree_create_validate.py — worktree name validation.

The naming convention <uuid>.<task-slug> is load-bearing: the Stop hook
(worktree_stop_cleanup.py) identifies session worktrees by scanning for
$CLAUDE_CODE_SESSION_ID in the directory name. Invalid names become orphans
that can never be auto-cleaned.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_hook_path = (
    Path(__file__).resolve().parents[1]
    / ".claude"
    / "hooks"
    / "worktree_create_validate.py"
)
_spec = importlib.util.spec_from_file_location("worktree_create_validate", _hook_path)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["worktree_create_validate"] = _mod
_spec.loader.exec_module(_mod)

validate_name = _mod.validate_name


_VALID = [
    ("b9395dee-d9fd-49e7-80a9-1f0f6bd0a0f6.auth-fix", "standard uuid.slug"),
    ("00000000-0000-0000-0000-000000000000.test", "zero uuid"),
    ("b9395dee-d9fd-49e7-80a9-1f0f6bd0a0f6.multi.dot.slug", "slug with dots"),
]

_INVALID = [
    ("", "empty string"),
    ("just-a-slug", "no uuid prefix"),
    ("b9395dee-d9fd-49e7-80a9-1f0f6bd0a0f6", "uuid only, no dot or slug"),
    ("b9395dee-d9fd-49e7-80a9-1f0f6bd0a0f6.", "uuid with dot but no slug"),
    ("not-a-uuid.some-slug", "invalid uuid format"),
    (".leading-dot", "leading dot, no uuid"),
]


@pytest.mark.parametrize(("name", "desc"), _VALID, ids=[v[1] for v in _VALID])
def test_valid_names(name: str, desc: str) -> None:
    assert validate_name(name) is True, f"should accept: {desc}"


@pytest.mark.parametrize(("name", "desc"), _INVALID, ids=[i[1] for i in _INVALID])
def test_invalid_names(name: str, desc: str) -> None:
    assert validate_name(name) is False, f"should reject: {desc}"
