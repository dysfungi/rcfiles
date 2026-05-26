#!/usr/bin/env bash
# Enforces git worktree isolation for Claude Code sessions.
#
# Usage: worktree-check.sh <session-start|pre-tool-use>
#
# session-start: prints a warning to stdout (injected into Claude's context)
# pre-tool-use:  exits 2 to block Write/Edit/NotebookEdit tool calls
#
# Touch .claude/worktree-exempt in the project root to bypass enforcement.
set -euo pipefail

mode="${1:-pre-tool-use}"

# Find the project root from CLAUDE_PROJECT_DIR or git
project_dir="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

# Bypass if escape hatch is set
if [[ -f "${project_dir}/.claude/worktree-exempt" ]]; then
  exit 0
fi

# Detect whether we are in a linked worktree.
# In the main worktree, git-dir and git-common-dir resolve to the same path.
# In a linked worktree, git-dir is inside .git/worktrees/<name>/, while
# git-common-dir is the main .git/ — so they differ.
git_dir="$(git rev-parse --git-dir 2>/dev/null)" || exit 0
git_common="$(git rev-parse --git-common-dir 2>/dev/null)" || exit 0

# Resolve to absolute paths for a reliable comparison
git_dir="$(cd "${git_dir}" && pwd)"
git_common="$(cd "${git_common}" && pwd)"

if [[ "${git_dir}" != "${git_common}" ]]; then
  # In a linked worktree — all clear
  exit 0
fi

# We are on the main worktree. Act based on mode.
case "${mode}" in
session-start)
  # Stdout is injected into Claude's context window by the SessionStart hook.
  # Use this to prime Claude with a visible reminder before it does anything.
  cat <<'EOF'
[WORKTREE ENFORCEMENT] You are on the main git worktree of this chezmoi repo.
Write, Edit, and NotebookEdit tool calls are BLOCKED until you enter a linked worktree.

Before making any file changes:
  1. Use the EnterWorktree tool to create an isolated worktree for this task.
  2. Register a todo.txt entry (see AGENTS.md "Multi-instance worktrees" section).

To bypass for a genuinely trivial edit: touch .claude/worktree-exempt
EOF
  exit 0
  ;;
pre-tool-use)
  # Exit 2 tells Claude Code to block the tool call and surface stderr to Claude.
  echo "BLOCKED: Write/Edit/NotebookEdit are disabled on the main worktree. Use EnterWorktree first, or touch .claude/worktree-exempt to bypass." >&2
  exit 2
  ;;
esac
