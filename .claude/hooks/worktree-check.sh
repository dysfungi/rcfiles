#!/usr/bin/env -S mise x -- bash
# shellcheck shell=bash
# Enforces git worktree isolation for Claude Code sessions.
#
# Usage: worktree-check.sh <session-start|pre-tool-use>
#
# session-start: prints a warning to stdout (injected into Claude's context)
# pre-tool-use:  exits 2 to block Write/Edit/NotebookEdit on repo files
#
# Bypass (per-session): touch .claude/worktree-exempt.$CLAUDE_CODE_SESSION_ID
# Bypass (global):      touch .claude/worktree-exempt
set -uo pipefail

mode="${1:-pre-tool-use}"

project_dir="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

# --- Worktree detection ---
# In a linked worktree, git-dir differs from git-common-dir.
git_dir="$(git rev-parse --git-dir 2>/dev/null)" || exit 0
git_common="$(git rev-parse --git-common-dir 2>/dev/null)" || exit 0
git_dir="$(cd "${git_dir}" && pwd)"
git_common="$(cd "${git_common}" && pwd)"

if [[ "${git_dir}" != "${git_common}" ]]; then
  exit 0
fi

# --- We are on the main worktree. ---
case "${mode}" in
session-start)
  cat <<EOF
[WORKTREE ENFORCEMENT] You are on the main git worktree of this chezmoi repo.
Write, Edit, and NotebookEdit tool calls targeting repo files are BLOCKED until you enter a linked worktree.

Before making any file changes:
  1. Create a worktree: git worktree add .worktrees/<task-slug> -b task/<task-slug>
  2. cd into it so CWD is inside the worktree.
  3. Register a todo.txt entry (see AGENTS.md "Multi-instance worktrees" section).

Per-session bypass: touch .claude/worktree-exempt.\$CLAUDE_CODE_SESSION_ID
EOF
  exit 0
  ;;
pre-tool-use)
  input="$(cat)"

  # --- Allow writes to files outside the repo ---
  file_path="$(printf '%s' "${input}" | jq -r '.tool_input.file_path // .tool_input.notebook_path // ""')"
  if [[ -n "${file_path}" ]]; then
    repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    if [[ -n "${repo_root}" ]]; then
      repo_root="${repo_root%/}/"
      if [[ "${file_path}" != "${repo_root}"* ]]; then
        exit 0
      fi
    fi
  fi

  # --- Per-session exempt ---
  session_id="$(printf '%s' "${input}" | jq -r '.session_id // ""')"
  sid="${session_id:-${CLAUDE_CODE_SESSION_ID:-}}"
  if [[ -n "${sid}" ]] && [[ -f "${project_dir}/.claude/worktree-exempt.${sid}" ]]; then
    exit 0
  fi

  # --- Global exempt (nuclear option) ---
  if [[ -f "${project_dir}/.claude/worktree-exempt" ]]; then
    exit 0
  fi

  echo "BLOCKED: Write/Edit/NotebookEdit on repo files are disabled on the main worktree. Create a worktree first, or touch .claude/worktree-exempt.\$CLAUDE_CODE_SESSION_ID to bypass this session only." >&2
  exit 2
  ;;
esac
