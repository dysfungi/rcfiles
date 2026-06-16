#!/usr/bin/env -S uv run --no-project
"""Blocks all tools in the root conversation thread except a narrow orchestration allowlist.

WHY this hook exists:
  Keeping the root context window small is the primary lever for long-running
  sessions. Any tool that returns raw text — file bodies, grep results, shell
  output, web pages, MCP fetches — dumps that content directly into the main
  context window, even if Claude only needs one line of it. The fix: run those
  tools inside a subagent, which gets its own isolated context window. Only the
  subagent's summary returns to the root thread.

  This hook enforces that pattern by hard-blocking everything except a narrow
  set of orchestration tools in the root thread. Subagents are exempt — they
  have their own context windows and can use any tool freely.

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

DESIGN — allowlist over denylist:
  Previous version used a denylist (BLOCKED_ROOT_TOOLS). That model is
  unsafe-by-default: any new tool — future Claude Code tool, new MCP server,
  etc. — is silently allowed until explicitly blocked. The allowlist inverts
  this: new tools are blocked by default and must be explicitly added to
  ALLOWED_ROOT_TOOLS to work in root. This is the right default for a
  context-discipline system where the expected case is "delegate to subagent."

ALLOWED_ROOT_TOOLS:
  Agent, Task           — spawning subagents (the whole point)
  Write, Edit,
  NotebookEdit          — file mutations (intentional; worktree guard handles isolation)
  AskUserQuestion,
  EnterPlanMode,
  ExitPlanMode          — UI and plan-mode transitions
  TodoWrite, TaskCreate,
  TaskUpdate, TaskGet,
  TaskList, TaskStop    — task tracking
  Workflow, Monitor,
  CronCreate, CronDelete,
  CronList, ScheduleWakeup,
  PushNotification      — orchestration and background scheduling
  EnterWorktree,
  ExitWorktree          — worktree management
  Skill                 — skill invocation (meta-level orchestration)
  DesignSync            — design system sync

Blocked by default (not in allowlist — representative examples):
  Read, Grep, Glob, Bash, PowerShell  — file/shell access (unbounded output)
  WebFetch, WebSearch                 — web content (pages/results land in context)
  mcp__*                              — MCP tool calls (can dump full page/ticket content)
  ReadMcpResourceTool,
  ListMcpResourcesTool                — MCP resource reads
  TaskOutput                          — retrieves raw background task output
  Any future tool not listed above    — safe-by-default

  Exception: Read of self-authored scratch paths is allowed (see below).

PATH-SCOPED READ EXEMPTION — Edit-requires-Read consistency fix:
  The harness requires a Read before any Edit call (the tool validates that
  the file was previously read in context). Edit/Write are on the allowlist
  because mutations don't dump content into context, but Read is not. This
  creates an inconsistency: editing any existing file in root is structurally
  impossible without the sentinel, even though Edit is "allowed."

  For self-authored scratch files this friction has zero context-savings
  payoff — plan files and memory files are small, bounded, and written by
  the agent itself. The Read-before-Edit requirement must be satisfiable.

  Fix: Read is allowed in root when the target resolves under:
    ~/.claude/plans/               — plan-mode scratch files
    ~/.claude/projects/*/memory/   — per-project memory files (one dir per
                                     project; slug is cwd with "/" → "-")

  Implementation: _is_scratch_path() resolves both the target and the anchor
  dirs before comparing (handles macOS /var → /private/var symlinks).
  resolve(strict=False) tolerates not-yet-existent paths. The memory dir
  match uses a depth check — after stripping ~/.claude/projects/, the
  second path segment must be "memory" — so project-root files like
  transcript.jsonl are correctly blocked.

EXEMPTION — sentinel file (requires explicit user permission):
  The sentinel file ~/.claude/root-guard-exempt disables the guard for the
  entire session. AGENTS MUST NOT create this file without explicit user
  approval — ask first, create only after the user confirms. The sentinel
  bypasses a deliberate user-configured safety constraint; silently creating
  it when the guard is inconvenient defeats its purpose.

  Mechanics: the Write tool can create the file (it's on the allowlist); Bash
  cannot (it's blocked). Once the file exists all tools unblock, including
  Bash, which can be used to delete it. Remove the file to re-enable the guard.

  There is intentionally NO plan-mode exemption and NO env-var escape hatch
  (chosen by the user). Plan mode already delegates exploration to the Plan
  subagent, so blocking root reads there is consistent. The sentinel file is
  the one-line escape when the guard is too rigid — but only with user consent.
"""

import json
import os
import sys
from pathlib import Path


def _is_scratch_path(file_path: str, home: Path) -> bool:
    """Return True if file_path resolves under a self-authored scratch dir.

    Allowed:
      ~/.claude/plans/**
      ~/.claude/projects/<slug>/memory/**

    Denied (representative): ~/.claude/projects/<slug>/transcript.jsonl
    """
    if not file_path:
        return False
    target = Path(file_path).resolve(strict=False)

    plans_dir = (home / ".claude" / "plans").resolve(strict=False)
    if target.is_relative_to(plans_dir):
        return True

    projects_dir = (home / ".claude" / "projects").resolve(strict=False)
    try:
        rel = target.relative_to(projects_dir)
    except ValueError:
        return False
    # rel.parts: ('<slug>', 'memory', ...) — require exactly 'memory' at index 1
    return len(rel.parts) >= 2 and rel.parts[1] == "memory"


# Tools allowed in the root thread. Everything else is blocked.
# Intentionally narrow: the root thread is for orchestration and decisions,
# not execution. Add a tool here only when it is genuinely orchestration-level
# (spawning work, writing results, tracking state) rather than reading/fetching.
ALLOWED_ROOT_TOOLS = frozenset(
    {
        # Delegation
        "Agent",
        "Task",
        # File mutations (intentional; worktree guard handles isolation)
        "Write",
        "Edit",
        "NotebookEdit",
        # UI / plan mode
        "AskUserQuestion",
        "EnterPlanMode",
        "ExitPlanMode",
        # Task tracking
        "TodoWrite",
        "TaskCreate",
        "TaskUpdate",
        "TaskGet",
        "TaskList",
        "TaskStop",
        # Orchestration / background scheduling
        "Workflow",
        "Monitor",
        "CronCreate",
        "CronDelete",
        "CronList",
        "ScheduleWakeup",
        "PushNotification",
        # Worktree management
        "EnterWorktree",
        "ExitWorktree",
        # Skills (meta-level orchestration; underlying tool calls are themselves guarded)
        "Skill",
        # Design system sync
        "DesignSync",
    }
)

_DELEGATE_HINT = (
    "Run this tool in a subagent (e.g. @scout, @distill, or a Task call). "
    "To disable the guard, ask the user for permission first, then create "
    "~/.claude/root-guard-exempt via the Write tool."
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

    # --- Root thread: enforce allowlist ---
    tool = payload.get("tool_name", "")
    if tool in ALLOWED_ROOT_TOOLS:
        return

    # --- Path-scoped Read exemption ---
    # Read of self-authored scratch files (plans, memory) is allowed so that
    # Edit-before-Read consistency holds without requiring the sentinel.
    if tool == "Read":
        file_path = payload.get("tool_input", {}).get("file_path", "")
        if _is_scratch_path(file_path, home):
            return

    print(
        f"BLOCKED in root thread: {tool}. {_DELEGATE_HINT}",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
