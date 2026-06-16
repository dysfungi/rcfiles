#!/usr/bin/env -S uv run --no-project
"""Blocks read-heavy and Bash tools in the root conversation thread.

WHY this hook exists:
  Keeping the root context window small is the primary lever for long-running
  sessions. Every Read, Grep, Glob, Bash, WebFetch, or WebSearch call in the
  root thread dumps raw output (file bodies, search hits, web pages) directly
  into the main context — even if Claude only reads one line of it, the whole
  response counts against the window. The fix: run those tools inside a
  subagent, which gets its own isolated context window. Only the subagent's
  summary (not the raw output) returns to the root thread.

  This hook enforces that pattern by hard-blocking the high-context tools
  in the root thread. Subagents are exempt — they have their own context
  windows and can use the tools freely.

DESIGN — agent_id presence as the discriminator:
  The PreToolUse hook payload includes an `agent_id` field that is PRESENT
  only when the hook fires inside a subagent, and ABSENT in the root thread
  (see Claude Code hooks docs: "present only when the hook fires inside a
  subagent call"). Checking agent_id absence is the only reliable root-vs-
  subagent signal available in PreToolUse — session_id and transcript_path
  are shared between root and subagents.

  Edge case: launching claude with `--agent <name>` adds agent_id/agent_type
  to the root session too. Since these sessions are launched without --agent
  (interactive use), that case is moot here but documented for clarity.

BLOCKED_ROOT_TOOLS:
  Read, Grep, Glob       — file reading/searching (high raw-output volume)
  Bash                   — shell commands (any Bash in root = raw output risk;
                           orchestration Bash like git/chezmoi/mise must run in
                           a subagent or with the sentinel file)
  WebFetch, WebSearch    — web content (entire pages/results land in context)

ALWAYS_ALLOWED_ROOT_TOOLS:
  Agent, Task            — spawning subagents (the whole point)
  Write, Edit, NotebookEdit — file mutations (root edits are intentional;
                              the worktree guard separately enforces isolation)
  TodoWrite, AskUserQuestion, ExitPlanMode — UI/task-management tools
  Skill                  — skill invocation (meta-level orchestration)
  MCP tools (mcp__*)     — MCP calls have unpredictable output size; allowed
                           because blocking them would break agentic workflows
                           that rely on structured MCP responses

EXEMPTION — sentinel file:
  Create ~/.claude/root-guard-exempt to disable the guard for the entire
  session (e.g., during interactive debugging or initial onboarding). Remove
  it to re-enable. This mirrors the worktree-exempt.$SESSION_ID pattern used
  by the worktree guard.

  IMPORTANT: Since Bash itself is blocked in root, you cannot use `touch` to
  create the sentinel from the CLI. Use the Write tool (it's not blocked) or
  create the file via an external shell (not inside a Claude session). Once
  the file exists, Bash unblocks and you can `rm` it normally from a subagent
  or from outside the session.

  There is intentionally NO plan-mode exemption and NO env-var escape hatch
  (chosen by the user). Plan mode already delegates exploration to the Plan
  subagent, so blocking root reads there is consistent. The sentinel file is
  the one-line escape when the guard is too rigid.
"""

import json
import os
import sys
from pathlib import Path

# Tools blocked in the root thread (any tool not listed here is allowed).
BLOCKED_ROOT_TOOLS = frozenset(
    {
        "Read",
        "Grep",
        "Glob",
        "Bash",
        "WebFetch",
        "WebSearch",
    }
)

_DELEGATE_HINT = (
    "Run this tool in a subagent (e.g. @scout, @distill, or a Task call). "
    "Or touch ~/.claude/root-guard-exempt to disable the guard for this session."
)


def main() -> None:
    payload = json.load(sys.stdin)

    # --- Subagent check (fast path) ---
    # agent_id is present only inside a subagent. Allow all tools there.
    if payload.get("agent_id"):
        return

    # --- Sentinel file exemption ---
    home = Path(os.path.expanduser("~"))
    if (home / ".claude" / "root-guard-exempt").exists():
        return

    # --- Root thread: enforce blocklist ---
    tool = payload.get("tool_name", "")
    if tool not in BLOCKED_ROOT_TOOLS:
        return

    print(
        f"BLOCKED in root thread: {tool}. {_DELEGATE_HINT}",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
