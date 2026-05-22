#!/usr/bin/env bash
# UserPromptSubmit hook: sets the tmux pane title from the current task label.
# Agent-written override (~/.claude/task-labels/$TMUX_PANE) takes precedence;
# falls back to the truncated user prompt from hook JSON stdin.
[[ -z "${TMUX:-}" ]] && exit 0

data=$(cat)
override="$HOME/.claude/task-labels/${TMUX_PANE}"
mkdir -p "$(dirname "$override")"

if [[ -f "$override" ]]; then
  label=$(cat "$override")
else
  prompt=$(printf '%s' "$data" | jq -r '.prompt // ""' 2>/dev/null || true)
  label=$(printf '%s' "$prompt" | tr '\n' ' ' | sed 's/^[[:space:]]*//' | cut -c1-40 | sed 's/[[:space:]]*$//')
fi

[[ -z "$label" ]] && exit 0
tmux select-pane -T "$label"
