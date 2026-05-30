#!/usr/bin/env -S uv run
"""Enforces git worktree isolation for Claude Code sessions.

WHY this hook exists:
  Multiple concurrent agent sessions on the same branch create undetectable
  file-edit races (last write wins). To prevent this, every session that modifies
  files must operate inside an isolated git worktree. This hook enforces that
  constraint at two points in the Claude Code lifecycle:

  - SessionStart: prints a warning into the agent's context window so it knows
    to create a worktree before attempting any mutations.
  - PreToolUse (Write/Edit/NotebookEdit): blocks the tool call with exit 2 if
    the session is still on the main worktree.

HOW worktree detection works:
  In a linked (non-main) worktree, `git rev-parse --git-dir` returns a path
  like `.git/worktrees/<name>`, while `--git-common-dir` returns the shared
  `.git` directory. When these resolve to the same real path, we're on the main
  worktree and mutations should be blocked. When they differ, we're inside a
  linked worktree and can proceed.

EXEMPTIONS:
  - Files outside the repo or inside `.claude/` (gitignored session infra)
  - Per-session: `touch .claude/worktree-exempt.$CLAUDE_CODE_SESSION_ID`
  - Global: `touch .claude/worktree-exempt`
  Agents must never create exemption files — they exist for human-only bypass.

USAGE:
  worktree_check.py session-start   → prints warning to stdout
  worktree_check.py pre-tool-use    → reads stdin JSON, exits 2 to block

Companion hook: bash_worktree_guard.py blocks mutating Bash commands using the
same worktree detection and exemption logic.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def is_main_worktree() -> bool:
    """True if CWD is on the main (non-linked) git worktree."""
    try:
        git_dir = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        git_common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return False
    return os.path.realpath(git_dir) == os.path.realpath(git_common)


def is_exempt(project_dir: str, payload: dict | None = None) -> bool:
    """Check per-session and global exemption files."""
    sid = ""
    if payload:
        sid = payload.get("session_id", "")
    if not sid:
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")

    if sid and Path(project_dir, ".claude", f"worktree-exempt.{sid}").exists():
        return True
    if Path(project_dir, ".claude", "worktree-exempt").exists():
        return True
    return False


def handle_session_start() -> None:
    print(
        "[WORKTREE ENFORCEMENT] You are on the main git worktree of this chezmoi repo.\n"
        "Write, Edit, and NotebookEdit tool calls targeting repo files are BLOCKED.\n"
        "Mutating Bash commands (git stash/commit/merge/rebase, sed -i, redirects, rm/mv/cp) are also BLOCKED.\n"
        "\n"
        "Before making any file changes:\n"
        '  1. Create a worktree: EnterWorktree name: "$CLAUDE_CODE_SESSION_ID.<task-slug>"\n'
        "  2. Register a todo.txt entry (see Multi-instance worktrees in your agent instructions).\n"
        "\n"
        "Per-session bypass: touch .claude/worktree-exempt.$CLAUDE_CODE_SESSION_ID"
    )


def handle_pre_tool_use(project_dir: str) -> None:
    payload = json.loads(sys.stdin.read())

    if is_exempt(project_dir, payload):
        return

    file_path = (
        payload.get("tool_input", {}).get("file_path")
        or payload.get("tool_input", {}).get("notebook_path")
        or ""
    )
    if file_path:
        repo_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if repo_root:
            repo_prefix = repo_root.rstrip("/") + "/"
            if not file_path.startswith(repo_prefix) or file_path.startswith(
                repo_prefix + ".claude/"
            ):
                return

    print(
        "BLOCKED: Write/Edit/NotebookEdit on repo files are disabled on the main worktree. "
        "Create a worktree first, or touch .claude/worktree-exempt.$CLAUDE_CODE_SESSION_ID "
        "to bypass this session only.",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre-tool-use"
    project_dir = os.environ.get(
        "CLAUDE_PROJECT_DIR",
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        or os.getcwd(),
    )

    if not is_main_worktree():
        return

    if mode == "session-start":
        handle_session_start()
    elif mode == "pre-tool-use":
        handle_pre_tool_use(project_dir)


if __name__ == "__main__":
    main()
