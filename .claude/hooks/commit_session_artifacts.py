#!/usr/bin/env -S uv run --no-project
"""Stop hook: auto-commits and pushes session artifact files.

WHY this hook exists:
  Other Stop hooks modify tracked files without committing:
  - migrate_permissions.py merges permissions into .claude/settings.json
  - worktree_stop_cleanup.py archives todo.txt entries into done.txt
  These changes sit unstaged until a human or future session notices.
  This hook commits and pushes them so they're durable immediately.

WHICH files it commits:
  .claude/settings.json, todo.txt, done.txt — session infrastructure files
  that are modified by Stop hooks or by agents during the session (e.g.,
  adding @worktree entries to todo.txt before creating a worktree).

ORDERING:
  Must run AFTER migrate_permissions.py and worktree_stop_cleanup.py in
  the Stop hook list, since those produce the changes this hook commits.

WHY pull-rebase + push:
  AGENTS.md requires "push immediately after every commit" and
  "pull-rebase-before-push." Multiple concurrent sessions may commit
  to these files, so rebase-before-push avoids non-fast-forward rejections.
  If push fails after one retry, the commit stays local — better than
  blocking session termination.

WHY it always exits 0:
  Stop hooks must not block session termination. A commit/push failure
  is annoying but not worth preventing the session from ending.
"""

import os
import subprocess
import sys
from pathlib import Path

ARTIFACT_FILES = [".claude/settings.json", "todo.txt", "done.txt"]


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)


def has_changes(repo_root: Path) -> list[str]:
    """Return artifact files with unstaged or staged changes."""
    result = git("diff", "--name-only", "HEAD", "--", *ARTIFACT_FILES, cwd=repo_root)
    changed = [f for f in result.stdout.strip().splitlines() if f]
    untracked = git(
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        *ARTIFACT_FILES,
        cwd=repo_root,
    )
    changed.extend(
        f for f in untracked.stdout.strip().splitlines() if f and f not in changed
    )
    return changed


def build_commit_message(changed: list[str], session_id: str) -> str:
    file_list = ", ".join(changed)
    username = os.environ.get("USER", "unknown")
    hostname = os.uname().nodename
    model = os.environ.get("CLAUDE_MODEL", "unknown")
    return (
        f"chore(session): auto-commit session artifacts\n"
        f"\n"
        f"Files: {file_list}\n"
        f"\n"
        f"Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>\n"
        f"Model: {model} (source: session)\n"
        f"Session-ID: {session_id} (source: session)\n"
        f"Username: {username} (source: session)\n"
        f"Hostname: {hostname} (source: session)"
    )


def main() -> None:
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    repo_root = Path(
        os.environ.get(
            "CLAUDE_PROJECT_DIR",
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
            ).stdout.strip(),
        )
    )

    if not repo_root.is_dir():
        return

    changed = has_changes(repo_root)
    if not changed:
        return

    git("add", "--", *changed, cwd=repo_root)
    msg = build_commit_message(changed, session_id)
    result = git("commit", "-m", msg, cwd=repo_root)
    if result.returncode != 0:
        print(f"WARNING: commit failed: {result.stderr.strip()}", file=sys.stderr)
        return

    for attempt in range(2):
        pull = git("pull", "--rebase", cwd=repo_root)
        if pull.returncode != 0:
            print(
                f"WARNING: pull --rebase failed (attempt {attempt + 1}): {pull.stderr.strip()}",
                file=sys.stderr,
            )
            if attempt == 1:
                return
            continue
        push = git("push", cwd=repo_root)
        if push.returncode == 0:
            return
        print(
            f"WARNING: push failed (attempt {attempt + 1}): {push.stderr.strip()}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
