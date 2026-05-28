#!/usr/bin/env -S mise x -- bash
# shellcheck shell=bash
# Blocks mutating Bash commands on the main git worktree.
#
# Targeted denylist — catches common agent patterns (git stash, sed -i,
# shell redirects, rm/mv/cp) while allowing all read-only operations.
# Not a sandbox: obfuscated mutations (eval, python one-liners) bypass this.
#
# Bypass (per-session): touch .claude/worktree-exempt.$CLAUDE_CODE_SESSION_ID
# Bypass (global):      touch .claude/worktree-exempt
set -uo pipefail

# --- Read stdin ---
input="$(cat)"

# --- Worktree detection ---
# In a linked worktree, git-dir differs from git-common-dir.
git_dir="$(git rev-parse --git-dir 2>/dev/null)" || exit 0
git_common="$(git rev-parse --git-common-dir 2>/dev/null)" || exit 0
git_dir="$(cd "${git_dir}" && pwd)"
git_common="$(cd "${git_common}" && pwd)"

if [[ "${git_dir}" != "${git_common}" ]]; then
  exit 0
fi

# --- We are on the main worktree. Check exemptions. ---
project_dir="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
session_id="$(printf '%s' "${input}" | jq -r '.session_id // ""')"
sid="${session_id:-${CLAUDE_CODE_SESSION_ID:-}}"

if [[ -n "${sid}" ]] && [[ -f "${project_dir}/.claude/worktree-exempt.${sid}" ]]; then
  exit 0
fi
if [[ -f "${project_dir}/.claude/worktree-exempt" ]]; then
  exit 0
fi

# --- Extract command ---
cmd="$(printf '%s' "${input}" | jq -r '.tool_input.command // ""')"
[[ -z "${cmd}" ]] && exit 0

# --- Extract git subcommand from a command segment ---
# Skips git global flags that take a value (-C, -c, --git-dir, --work-tree, --namespace).
# Uses awk (portable, no grep -P needed).
git_subcmd() {
  awk '{
    found_git = 0
    for (i = 1; i <= NF; i++) {
      if ($i == "git") { found_git = 1; i++; break }
    }
    if (!found_git) exit
    for (; i <= NF; i++) {
      tok = $i
      if (tok == "-C" || tok == "-c" || tok == "--work-tree" || tok == "--git-dir" || tok == "--namespace") {
        i++; continue
      }
      if (tok ~ /^-/) continue
      print tok; exit
    }
  }' <<<"$1"
}

# --- Check a single command segment against the denylist ---
# Returns 1 and prints a message to stderr if blocked, 0 if allowed.
check_segment() {
  local seg="$1"
  # Trim leading whitespace
  seg="${seg#"${seg%%[![:space:]]*}"}"
  [[ -z "${seg}" ]] && return 0

  # --- Output redirects (>, >>) ---
  # Exclude 2>, 2>>, >&, &> by requiring a non-2/& char (or start of string) before >.
  # Use two grep -E passes: match > or >>, then exclude if preceded by 2 or &.
  if command grep -qE '[^2&]>{1,2}[^&]|^>{1,2}[^&]' <<<"${seg}"; then
    echo "BLOCKED on main worktree: output redirect (>, >>). Create a worktree first." >&2
    return 1
  fi

  # --- tee (always writes to a file) ---
  if command grep -qE '(^|\|)[[:space:]]*tee([[:space:]]|$)' <<<"${seg}"; then
    echo "BLOCKED on main worktree: tee (writes to file). Create a worktree first." >&2
    return 1
  fi

  # --- sed -i (in-place edit) ---
  local seg_trimmed="${seg#"${seg%%[![:space:]]*}"}"
  if [[ "${seg_trimmed}" == sed\ * ]] || [[ "${seg_trimmed}" == sed ]]; then
    if command grep -qE '(^|[[:space:]])-[a-zA-Z]*i([[:space:]]|$)' <<<"${seg}"; then
      echo "BLOCKED on main worktree: sed -i (in-place edit). Create a worktree first." >&2
      return 1
    fi
  fi

  # --- rm, mv, cp ---
  if command grep -qE '^[[:space:]]*(rm|mv|cp)[[:space:]]' <<<"${seg}"; then
    local op
    op="$(command grep -oE '^[[:space:]]*(rm|mv|cp)' <<<"${seg}" | tr -d '[:space:]')"
    echo "BLOCKED on main worktree: ${op} (file operation). Create a worktree first." >&2
    return 1
  fi

  # --- git mutations ---
  if command grep -qE '^[[:space:]]*git([[:space:]]|$)' <<<"${seg}"; then
    local subcmd
    subcmd="$(git_subcmd "${seg}")"

    case "${subcmd:-}" in
    # Explicitly mutating: block
    add | am | apply | checkout | cherry-pick | clean | commit | fast-import | \
      merge | mv | rebase | reset | restore | revert | rm | update-index | update-ref)
      echo "BLOCKED on main worktree: git ${subcmd} (mutating). Create a worktree first." >&2
      return 1
      ;;
    stash)
      # Only 'git stash list' and 'git stash show' are safe
      if ! command grep -qE 'git[[:space:]]+stash[[:space:]]+(list|show)([[:space:]]|$)' <<<"${seg}"; then
        echo "BLOCKED on main worktree: git stash (mutating). Use 'git stash list'/'git stash show', or create a worktree first." >&2
        return 1
      fi
      ;;
      # All other subcommands (status, diff, log, push, fetch, pull, branch, tag,
      # worktree, config, ls-files, rev-parse, blame, etc.) are allowed.
    esac
  fi

  return 0
}

# --- Split compound commands and check each segment ---
# Normalize &&, ||, ; to newlines, then check each segment.
# Note: characters inside quotes are not handled specially (best-effort, not a sandbox).
normalized="${cmd//&&/$'\n'}"
normalized="${normalized//||/$'\n'}"
normalized="${normalized//;/$'\n'}"

while IFS= read -r segment; do
  [[ -z "${segment// /}" ]] && continue
  # Split on pipes and check each stage
  IFS='|' read -ra pipe_parts <<<"${segment}"
  for part in "${pipe_parts[@]}"; do
    check_segment "${part}" || exit 2
  done
done <<<"${normalized}"

exit 0
