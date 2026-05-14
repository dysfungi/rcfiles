#!/usr/bin/env python3
import json
import os
import sys
import subprocess

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
    info_parts.append(f"ctx:{round(used)}%")
if model:
    info_parts.append(model)

line1 = f"┬─[{abbreviated}]"
if branch:
    line1 += f"─[{branch}]"
if venv:
    line1 += f"─({venv})"

line2 = f"╰─[{' | '.join(info_parts)}]─✦"

print(f"{line1}\n{line2}", end="")
