#!/usr/bin/env -S mise x -- python3
"""WorktreeCreate hook: validates name follows <uuid>.<task-slug> convention.

Reads JSON from stdin (Claude Code hook protocol).
Exits 2 to block creation if name does not match the required format.
"""

import json
import sys
import uuid

payload = json.loads(sys.stdin.read())
name = payload.get("name", "")

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
