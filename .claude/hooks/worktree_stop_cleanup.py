#!/usr/bin/env -S mise x -- python3
"""Stop hook: auto-removes worktrees belonging to the current session.

Finds worktrees whose path contains $CLAUDE_CODE_SESSION_ID, then:
  - Merged/empty: removes worktree + branch silently, archives todo.txt entry
  - Unmerged: warns to stderr and leaves in place
  - Prunable (dir already gone): runs git worktree prune

Exits 0 always — Stop hooks must not block session termination.
"""

import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return run(["git", *args], cwd=cwd)


def parse_worktrees(porcelain: str) -> list[dict]:
    """Parse `git worktree list --porcelain` into a list of dicts."""
    worktrees = []
    current: dict = {}
    for line in porcelain.splitlines():
        if not line:
            if current:
                worktrees.append(current)
                current = {}
        elif line.startswith("worktree "):
            current["path"] = line[len("worktree ") :]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch refs/heads/") :]
        elif line == "prunable":
            current["prunable"] = True
        elif line == "bare":
            current["bare"] = True
    if current:
        worktrees.append(current)
    return worktrees


def is_merged(repo_root: Path, branch: str) -> bool:
    """True if branch has no commits ahead of main."""
    result = git("diff", f"main...{branch}", "--quiet", cwd=repo_root)
    return result.returncode == 0


def archive_todo_entry(repo_root: Path, session_id: str) -> None:
    """Move matching @worktree: todo.txt entries to done.txt."""
    todo_path = repo_root / "todo.txt"
    done_path = repo_root / "done.txt"
    if not todo_path.exists():
        return

    today = date.today().isoformat()
    pattern = re.compile(rf"@worktree:[^\s]*{re.escape(session_id)}")

    kept, archived = [], []
    for line in todo_path.read_text().splitlines(keepends=True):
        if pattern.search(line):
            # Strip leading priority marker if present, prepend done prefix
            clean = re.sub(r"^\([A-Z]\) ", "", line.rstrip("\n"))
            archived.append(f"x {today} {clean}\n")
        else:
            kept.append(line)

    if archived:
        todo_path.write_text("".join(kept))
        with done_path.open("a") as f:
            f.writelines(archived)


def main() -> None:
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not session_id:
        return

    result = git("worktree", "list", "--porcelain")
    if result.returncode != 0:
        return

    worktrees = parse_worktrees(result.stdout)
    # Skip the main worktree (first entry, no session ID in path)
    session_worktrees = [wt for wt in worktrees[1:] if session_id in wt.get("path", "")]
    if not session_worktrees:
        return

    # Derive repo root from the main worktree path
    repo_root = Path(worktrees[0]["path"])
    prunable_found = False

    for wt in session_worktrees:
        path = Path(wt["path"])
        branch = wt.get("branch", "")

        if wt.get("prunable"):
            prunable_found = True
            continue

        if not branch:
            print(
                f"WARNING: Worktree {path} has no branch; skipping cleanup.",
                file=sys.stderr,
            )
            continue

        if not is_merged(repo_root, branch):
            print(
                f"WARNING: Worktree '{path}' (branch '{branch}') has unmerged commits.\n"
                "         Not removing — merge or cherry-pick to main first, then:\n"
                f"         git worktree remove {path}\n"
                f"         git branch -d {branch}",
                file=sys.stderr,
            )
            continue

        git("worktree", "remove", str(path))
        git("branch", "-d", branch)

    if prunable_found:
        git("worktree", "prune")

    archive_todo_entry(repo_root, session_id)


if __name__ == "__main__":
    main()
