#!/usr/bin/env -S uv run
"""Blocks mutating Bash commands on the main git worktree.

WHY this hook exists:
  worktree_check.py blocks Write/Edit/NotebookEdit tool calls, but agents can
  also mutate files through the Bash tool (git commit, sed -i, shell redirects,
  rm/mv/cp). This companion hook intercepts Bash tool calls and blocks known
  mutation patterns while allowing all read-only operations.

DESIGN — targeted denylist, not a sandbox:
  This is a best-effort guardrail, not a security sandbox. It catches common
  agent mutation patterns (the operations Claude Code agents actually use) but
  cannot detect obfuscated mutations (eval, python one-liners, base64-decoded
  commands). The goal is to prevent accidental file-edit races between concurrent
  sessions, not to sandbox untrusted code.

HOW command parsing works:
  1. Split compound commands on `&&`, `||`, `;` → then split each on `|`
  2. Check each segment against the denylist:
     - Output redirects (>, >>) excluding stderr redirects (2>, &>)
     - tee, sed -i, rm, mv, cp
     - Git mutations (explicit subcommand list — add, commit, merge, rebase, etc.)
     - Git stash (only list/show allowed)
  3. git_subcmd() skips git global flags (-C, -c, --work-tree, --git-dir,
     --namespace) that take a value argument, to find the actual subcommand.

  The command-splitting approach (string.replace, not shell parsing) is
  intentionally simple and may produce false positives on edge cases with
  quoted strings containing delimiters. This is acceptable — false positives
  just ask the agent to use a worktree, which it should be doing anyway.

EXEMPTIONS: same as worktree_check.py — per-session file, global file.

Companion hook: worktree_check.py blocks Write/Edit/NotebookEdit.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

MUTATING_GIT_SUBCMDS = frozenset(
    {
        "add",
        "am",
        "apply",
        "checkout",
        "cherry-pick",
        "clean",
        "commit",
        "fast-import",
        "merge",
        "mv",
        "rebase",
        "reset",
        "restore",
        "revert",
        "rm",
        "update-index",
        "update-ref",
    }
)

GIT_FLAGS_WITH_VALUE = frozenset(
    {"-C", "-c", "--work-tree", "--git-dir", "--namespace"}
)


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


def is_exempt(project_dir: str, payload: dict) -> bool:
    """Check per-session and global exemption files."""
    sid = payload.get("session_id", "") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if sid and Path(project_dir, ".claude", f"worktree-exempt.{sid}").exists():
        return True
    return Path(project_dir, ".claude", "worktree-exempt").exists()


def git_subcmd(segment: str) -> str:
    """Extract the git subcommand from a command string, skipping global flags."""
    tokens = segment.split()
    i = 0
    while i < len(tokens):
        if tokens[i] == "git":
            i += 1
            break
        i += 1
    else:
        return ""

    while i < len(tokens):
        tok = tokens[i]
        if tok in GIT_FLAGS_WITH_VALUE:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        return tok
    return ""


def check_segment(segment: str) -> str | None:
    """Return a block reason if segment is mutating, else None."""
    seg = segment.lstrip()
    if not seg:
        return None

    # Output redirects (>, >>), excluding stderr (2>, 2>>, &>, >&)
    if re.search(r"(?<![2&])>{1,2}(?!&)", seg) or re.match(r">{1,2}(?!&)", seg):
        return "output redirect (>, >>)"

    # tee
    if re.search(r"(^|\|)\s*tee(\s|$)", seg):
        return "tee (writes to file)"

    # sed -i
    seg_stripped = seg.lstrip()
    if seg_stripped.startswith("sed ") or seg_stripped == "sed":
        if re.search(r"(^|\s)-[a-zA-Z]*i(\s|$)", seg):
            return "sed -i (in-place edit)"

    # rm, mv, cp
    match = re.match(r"\s*(rm|mv|cp)\s", seg)
    if match:
        return f"{match.group(1)} (file operation)"

    # Git mutations
    if re.match(r"\s*git(\s|$)", seg):
        subcmd = git_subcmd(seg)
        if subcmd in MUTATING_GIT_SUBCMDS:
            return f"git {subcmd} (mutating)"
        if subcmd == "stash" and not re.search(r"git\s+stash\s+(list|show)(\s|$)", seg):
            return "git stash (mutating)"

    return None


def main() -> None:
    payload = json.loads(sys.stdin.read())

    if not is_main_worktree():
        return

    project_dir = os.environ.get(
        "CLAUDE_PROJECT_DIR",
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        or os.getcwd(),
    )

    if is_exempt(project_dir, payload):
        return

    cmd = payload.get("tool_input", {}).get("command", "")
    if not cmd:
        return

    # Split compound commands, then split pipes, check each segment
    normalized = cmd.replace("&&", "\n").replace("||", "\n").replace(";", "\n")
    for line in normalized.splitlines():
        if not line.strip():
            continue
        for part in line.split("|"):
            reason = check_segment(part)
            if reason:
                print(
                    f"BLOCKED on main worktree: {reason}. Create a worktree first.",
                    file=sys.stderr,
                )
                sys.exit(2)


if __name__ == "__main__":
    main()
