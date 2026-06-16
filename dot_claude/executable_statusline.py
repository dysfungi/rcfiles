#!/usr/bin/env python3
"""Claude Code statusline script.

Renders a two-line statusline showing: pane title, abbreviated cwd, git branch,
virtualenv, context-window usage %, and model name.

Context-window thresholds (CTX_WARN_PCT / CTX_CRIT_PCT):
  These are intentionally aggressive — the goal is to nudge delegation into a
  subagent *early*, while delegating is still cheap. By 20% (warn) you should
  already be delegating reads to @scout/@distill. By 25% (crit) you're in
  expensive-to-fix territory. Tune these constants to match your workflow.
"""

import json
import os
import subprocess
import sys

# Context-window color thresholds (in %).
# Below CTX_WARN_PCT: default terminal color.
# CTX_WARN_PCT to CTX_CRIT_PCT: yellow — delegate reads now.
# At or above CTX_CRIT_PCT: red — reset context or you're paying for it.
CTX_WARN_PCT = 20
CTX_CRIT_PCT = 25

# ANSI escape codes (reset is always applied after the colored segment).
_ANSI_YELLOW = "\033[33m"
_ANSI_RED = "\033[31m"
_ANSI_RESET = "\033[0m"


def ctx_colored(pct: int) -> str:
    """Return the ctx:NN% string with ANSI color applied if above thresholds."""
    text = f"ctx:{pct}%"
    if pct >= CTX_CRIT_PCT:
        return f"{_ANSI_RED}{text}{_ANSI_RESET}"
    if pct >= CTX_WARN_PCT:
        return f"{_ANSI_YELLOW}{text}{_ANSI_RESET}"
    return text


data = json.load(sys.stdin)
home = os.path.expanduser("~")

raw_dir = data.get("workspace", {}).get("current_dir") or data.get("cwd", "")
model = data.get("model", {}).get("display_name", "")
used = data.get("context_window", {}).get("used_percentage")
branch = (
    data.get("worktree", {}).get("branch")
    or data.get("workspace", {}).get("git_worktree")
    or subprocess.run(
        ["git", "-C", raw_dir, "branch", "--show-current"],
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    ).stdout.strip()
)

pane_title = ""
if os.environ.get("TMUX"):
    pane_title = subprocess.run(
        ["tmux", "display-message", "-p", "#{pane_title}"],
        capture_output=True,
        text=True,
    ).stdout.strip()

# Abbreviate path: collapse $HOME → ~, shorten middle segments to first letter
path = raw_dir.replace(home, "~", 1)
parts = path.split("/")
abbreviated = "/".join(
    p if i == 0 or i == len(parts) - 1 or p in ("", "~") else p[0]
    for i, p in enumerate(parts)
)

venv = (
    os.path.basename(os.environ["VIRTUAL_ENV"]) if os.environ.get("VIRTUAL_ENV") else ""
)

info_parts = []
if used is not None:
    info_parts.append(ctx_colored(round(used)))
if model:
    info_parts.append(model)

line1 = "┬─"
if pane_title:
    line1 += f"{{{pane_title}}}─"
line1 += f"[{abbreviated}]"
if branch:
    line1 += f"─[{branch}]"
if venv:
    line1 += f"─({venv})"

line2 = f"╰─[{' | '.join(info_parts)}]─✦"

print(f"{line1}\n{line2}", end="")
