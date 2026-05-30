"""Tests for .claude/hooks/bash_worktree_guard.py — the Bash mutation guard.

These parametrized tables serve as the executable spec for which Bash commands
are allowed vs blocked on the main worktree. Adding a new row documents and
enforces the behavior in one place.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Import the hook module directly by path (it's a standalone script, not a package).
_hook_path = (
    Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "bash_worktree_guard.py"
)
_spec = importlib.util.spec_from_file_location("bash_worktree_guard", _hook_path)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["bash_worktree_guard"] = _mod
_spec.loader.exec_module(_mod)

check_segment = _mod.check_segment
git_subcmd = _mod.git_subcmd


# ---------------------------------------------------------------------------
# check_segment: allowed commands (should return None)
# ---------------------------------------------------------------------------

_ALLOWED = [
    # Read-only git
    ("git status", "read-only status"),
    ("git diff", "read-only diff"),
    ("git log --oneline", "read-only log"),
    ("git show HEAD", "read-only show"),
    ("git branch -a", "read-only branch list"),
    ("git pull --rebase", "pull"),
    ("git push", "push"),
    ("git push --force-with-lease", "push with lease"),
    ("git fetch origin", "fetch"),
    ("git remote -v", "remote"),
    ("git stash list", "stash list (read-only)"),
    ("git stash show stash@{0}", "stash show (read-only)"),
    # Merge-back flow: ff-only is explicitly allowed
    ("git merge --ff-only worktree-branch", "ff-only merge (merge-back flow)"),
    ("git merge --ff-only origin/main", "ff-only merge with remote ref"),
    # Stderr redirects (not file mutations)
    ("some-cmd 2>/dev/null", "stderr redirect to /dev/null"),
    ("some-cmd 2>&1", "stderr merge"),
    ("some-cmd &>/dev/null", "combined redirect to /dev/null"),
    # Read-only todo.sh
    ("todo.sh list", "todo.sh list (read-only)"),
    ("todo.sh listall", "todo.sh listall (read-only)"),
    ("todo.sh listpri", "todo.sh listpri (read-only)"),
    ("todo.sh listproj", "todo.sh listproj (read-only)"),
    ("todo.sh listcon", "todo.sh listcon (read-only)"),
    ("todo.sh listaddons", "todo.sh listaddons (read-only)"),
    ("todo.sh listfile", "todo.sh listfile (read-only)"),
    ("todo.sh ls", "todo.sh ls (read-only alias)"),
    ("todo.sh lsa", "todo.sh lsa (read-only alias)"),
    ("todo.sh lsc", "todo.sh lsc (read-only alias)"),
    ("todo.sh lsp", "todo.sh lsp (read-only alias)"),
    ("todo.sh lsprj", "todo.sh lsprj (read-only alias)"),
    ("todo.sh lf @worktree", "todo.sh lf with filter (read-only alias)"),
    ("todo.sh help", "todo.sh help"),
    ("todo.sh shorthelp", "todo.sh shorthelp"),
    # Plain commands
    ("echo hello", "echo"),
    ("ls -la", "ls"),
    ("cat file.txt", "cat"),
    ("grep -r pattern .", "grep"),
    ("find . -name '*.py'", "find"),
]


@pytest.mark.parametrize(("cmd", "desc"), _ALLOWED, ids=[a[1] for a in _ALLOWED])
def test_allowed_commands(cmd: str, desc: str) -> None:
    assert check_segment(cmd) is None, f"should allow: {desc}"


# ---------------------------------------------------------------------------
# check_segment: blocked commands (should return a reason string)
# ---------------------------------------------------------------------------

_BLOCKED = [
    # Git mutations
    ("git add .", "git add"),
    ("git commit -m 'test'", "git commit"),
    ("git merge some-branch", "bare git merge (no --ff-only)"),
    ("git merge --no-ff some-branch", "git merge --no-ff"),
    ("git rebase main", "git rebase"),
    ("git reset HEAD~1", "git reset"),
    ("git checkout other-branch", "git checkout"),
    ("git cherry-pick abc123", "git cherry-pick"),
    ("git revert HEAD", "git revert"),
    ("git rm file.txt", "git rm"),
    ("git mv old.txt new.txt", "git mv"),
    ("git clean -fd", "git clean"),
    ("git restore --staged file.txt", "git restore"),
    ("git apply patch.diff", "git apply"),
    ("git am mbox.patch", "git am"),
    ("git fast-import", "git fast-import"),
    ("git update-index --add file", "git update-index"),
    ("git update-ref refs/heads/main HEAD", "git update-ref"),
    # Git stash mutations
    ("git stash", "bare git stash"),
    ("git stash push -m 'wip'", "git stash push"),
    ("git stash pop", "git stash pop"),
    ("git stash drop", "git stash drop"),
    ("git stash apply", "git stash apply"),
    # todo.sh mutations
    ("todo.sh add foo bar", "todo.sh add"),
    ("todo.sh do 5", "todo.sh do"),
    ("todo.sh del 3", "todo.sh del"),
    ("todo.sh pri 3 A", "todo.sh pri"),
    ("todo.sh depri 3", "todo.sh depri"),
    ("todo.sh append 3 more text", "todo.sh append"),
    ("todo.sh prepend 3 prefix", "todo.sh prepend"),
    ("todo.sh replace 3 new text", "todo.sh replace"),
    ("todo.sh move 3 project.txt", "todo.sh move"),
    ("todo.sh archive", "todo.sh archive"),
    ("todo add something", "todo add (alias)"),
    # File operations
    ("rm file.txt", "rm"),
    ("rm -rf dir/", "rm -rf"),
    ("mv old.txt new.txt", "mv"),
    ("cp src.txt dst.txt", "cp"),
    # Output redirects
    ("echo hello > file.txt", "stdout redirect >"),
    ("echo hello >> file.txt", "stdout append >>"),
    # tee
    ("cat input | tee output.txt", "tee in pipeline"),
    ("tee output.txt", "bare tee"),
    # sed -i
    ("sed -i 's/old/new/' file.txt", "sed -i"),
    ("sed -i.bak 's/old/new/' file.txt", "sed -i with backup"),
]


@pytest.mark.parametrize(("cmd", "desc"), _BLOCKED, ids=[b[1] for b in _BLOCKED])
def test_blocked_commands(cmd: str, desc: str) -> None:
    result = check_segment(cmd)
    assert result is not None, f"should block: {desc}"


# ---------------------------------------------------------------------------
# git_subcmd: flag-skipping to find the actual subcommand
# ---------------------------------------------------------------------------

_SUBCMD_CASES = [
    ("git status", "status"),
    ("git -C /some/path status", "status"),
    ("git -c core.autocrlf=true commit -m 'x'", "commit"),
    ("git --work-tree /path --git-dir /path/.git log", "log"),
    ("git --namespace foo push", "push"),
    ("git -C /a -c x=y -C /b merge --ff-only branch", "merge"),
    ("git", ""),
    ("not-git status", ""),
    ("git --verbose", ""),
]


@pytest.mark.parametrize(
    ("cmd", "expected"),
    _SUBCMD_CASES,
    ids=[c[0].replace(" ", "_")[:50] for c in _SUBCMD_CASES],
)
def test_git_subcmd(cmd: str, expected: str) -> None:
    assert git_subcmd(cmd) == expected
