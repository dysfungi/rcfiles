"""Tests for .claude/hooks/worktree_stop_cleanup.py — the session worktree reaper.

This artifact has a WHEN concern and a WHAT concern, tested separately:

  WHEN it runs (wiring guard) — the reaper must fire on the root-only `SessionEnd`
    event, NOT the per-turn `Stop` event. `Stop` fires at every turn boundary, so a
    freshly-entered or still-in-use worktree (0 commits ahead of main ⇒ reads as
    "merged") got reaped out from under background subagents mid-session. The wiring
    guard is the primary regression test: it parses settings.json and asserts the
    reaper command appears under SessionEnd and not under Stop.

  WHAT it does (behavior spec) — given the right lifecycle event, the reaper removes
    merged/0-commit session worktrees, preserves worktrees with commits ahead of main
    (work-preservation), and ignores worktrees scoped to a different session uuid
    (multi-instance safety).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Import the hook module directly by path (it's a standalone script, not a package).
_hook_path = _REPO_ROOT / ".claude" / "hooks" / "worktree_stop_cleanup.py"
_spec = importlib.util.spec_from_file_location("worktree_stop_cleanup", _hook_path)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["worktree_stop_cleanup"] = _mod
_spec.loader.exec_module(_mod)


# ---------------------------------------------------------------------------
# Wiring guard — the reaper must be on SessionEnd, never on per-turn Stop.
# ---------------------------------------------------------------------------

_REAPER = "worktree_stop_cleanup.py"


def _commands_for_event(event: str) -> list[str]:
    """All hook command strings configured under a settings.json event."""
    settings = json.loads((_REPO_ROOT / ".claude" / "settings.json").read_text())
    commands: list[str] = []
    for entry in settings.get("hooks", {}).get(event, []):
        for hook in entry.get("hooks", []):
            commands.append(hook.get("command", ""))
    return commands


@pytest.mark.parametrize(
    "event,expected_present",
    [
        ("SessionEnd", True),
        ("Stop", False),
    ],
    ids=["wired-to-SessionEnd", "not-wired-to-Stop"],
)
def test_reaper_wiring(event: str, expected_present: bool) -> None:
    present = any(_REAPER in cmd for cmd in _commands_for_event(event))
    assert present is expected_present, (
        f"{_REAPER} should{'' if expected_present else ' NOT'} be wired to {event!r}; "
        f"got commands {_commands_for_event(event)!r}"
    )


# ---------------------------------------------------------------------------
# Behavior spec — reap merged, preserve unmerged, ignore other sessions.
# ---------------------------------------------------------------------------

_SESSION = "11111111-1111-1111-1111-111111111111"
_OTHER_SESSION = "99999999-9999-9999-9999-999999999999"

_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _clean_env(home: Path) -> dict[str, str]:
    """os.environ with GIT_* stripped, HOME pinned, and a test identity.

    Stripping GIT_* prevents pre-commit's leaked GIT_DIR from redirecting these
    git calls into the real chezmoi repo (see .tests/conftest.py).
    """
    base = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return {**base, **_GIT_IDENTITY, "HOME": str(home)}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=_clean_env(repo),
    )


def test_reaper_behavior(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The git_repo fixture seeds one commit; pin it to an explicit `main` branch,
    # since the reaper's merge check is `git diff main...<branch>`.
    _git(git_repo, "branch", "-M", "main")

    wt_base = tmp_path / "worktrees"
    wt_base.mkdir()

    # (1) Merged session worktree: branched from main, no commits ahead → reaped.
    merged_wt = wt_base / f"{_SESSION}.merged"
    _git(git_repo, "worktree", "add", "-b", "merged-branch", str(merged_wt), "main")

    # (2) Session worktree with a commit ahead of main → preserved (work safety).
    ahead_wt = wt_base / f"{_SESSION}.ahead"
    _git(git_repo, "worktree", "add", "-b", "ahead-branch", str(ahead_wt), "main")
    (ahead_wt / "new_file.txt").write_text("work in progress\n")
    _git(ahead_wt, "add", "new_file.txt")
    _git(ahead_wt, "commit", "-m", "wip")

    # (3) Worktree scoped to a DIFFERENT session uuid → untouched (multi-instance).
    other_wt = wt_base / f"{_OTHER_SESSION}.merged"
    _git(git_repo, "worktree", "add", "-b", "other-branch", str(other_wt), "main")

    # Invoke the reaper exactly as SessionEnd would: session id from env, cwd in
    # the repo. Strip GIT_* so the in-process git calls hit git_repo, not the real
    # chezmoi repo.
    for var in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _SESSION)
    monkeypatch.setenv("HOME", str(git_repo))
    monkeypatch.chdir(git_repo)

    _mod.main()

    assert not merged_wt.exists(), "merged 0-commit session worktree should be reaped"
    assert ahead_wt.exists(), "worktree with commits ahead of main must be preserved"
    assert other_wt.exists(), "worktree from a different session must be untouched"
