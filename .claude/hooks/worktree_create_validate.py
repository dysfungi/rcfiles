#!/usr/bin/env -S uv run
"""WorktreeCreate factory hook: validates the name, creates the worktree, echoes the path.

WHY this is a WorktreeCreate factory (not a PreToolUse validator):
  The WorktreeCreate hook type fully replaces Claude Code's default worktree
  creation — Claude Code does nothing itself and expects this hook to both
  create the worktree AND print its absolute path to stdout.

  Using PreToolUse is NOT an alternative: EnterWorktree is not a Bash tool,
  so PreToolUse matchers cannot intercept it.

WHY the UUID prefix is enforced here:
  worktree_stop_cleanup.py (the Stop hook) identifies worktrees to auto-remove
  by scanning `git worktree list` for paths that contain $CLAUDE_CODE_SESSION_ID.
  The naming convention `<session-uuid>.<task-slug>` is the ONLY breadcrumb
  linking a worktree to the session that created it — there is no external
  registry. If a worktree is created without the UUID prefix, the Stop hook
  cannot find it, and it becomes a permanent orphan that must be cleaned up
  manually. Enforcing the format at creation time (exit 2 before touching the
  filesystem) is the only reliable gate.

Protocol (Claude Code WorktreeCreate):
  - Read JSON payload from stdin; payload includes `name` field.
  - Exit 2 BEFORE creating to block with a descriptive error to stderr.
  - On success: create the worktree, print its absolute path to stdout, exit 0.
  - On creation failure: print stderr from git, exit non-zero.
"""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path


def main() -> None:
    payload = json.loads(sys.stdin.read())
    name = payload.get("name", "")

    # Validate name format: <uuid>.<task-slug>
    # The UUID prefix is required so worktree_stop_cleanup.py can identify
    # this worktree by session ID during Stop hook cleanup. See module docstring.
    parts = name.split(".", 1)
    valid = len(parts) == 2 and bool(parts[1])
    if valid:
        try:
            uuid.UUID(parts[0])
        except ValueError:
            valid = False

    if not valid:
        print(
            f"BLOCKED: Worktree name '{name}' does not follow the required format.\n"
            "Required: <session-uuid>.<task-slug>\n"
            "Example:  b9395dee-d9fd-49e7-80a9-1f0f6bd0a0f6.mason-ocaml-fix\n"
            "Use $CLAUDE_CODE_SESSION_ID as the UUID prefix.",
            file=sys.stderr,
        )
        sys.exit(2)

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
    worktree_path = project_dir / ".claude" / "worktrees" / name
    branch = f"worktree-{name}"

    result = subprocess.run(
        ["git", "worktree", "add", str(worktree_path), "-b", branch],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)

    # Echo path to stdout — required by the WorktreeCreate factory protocol.
    print(str(worktree_path))


if __name__ == "__main__":
    main()
