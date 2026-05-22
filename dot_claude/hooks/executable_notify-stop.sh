#!/usr/bin/env bash
# Stop hook: send ntfy.sh notification when away mode is active (~/.claude/away sentinel).
[[ ! -f "$HOME/.claude/away" ]] && exit 0

topic="${NTFY_TOPIC:-dfrank-claude-$(hostname -s | tr '[:upper:]' '[:lower:]')}"
label_file="$HOME/.claude/task-labels/${TMUX_PANE}"
msg=$([[ -f "$label_file" ]] && cat "$label_file" || echo "Turn complete — input needed")

curl -s \
  -H "Title: Claude waiting" \
  -H "Priority: default" \
  -d "$msg" \
  "https://ntfy.sh/${topic}" \
  >/dev/null 2>&1

exit 0
