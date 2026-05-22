#!/usr/bin/env bash
# Stop hook: send ntfy.sh notification when away mode is active (~/.claude/away sentinel).
# Must run BEFORE the "rm -f task-labels" Stop hook so the label file is still readable.
[[ ! -f "$HOME/.claude/away" ]] && exit 0

topic="${NTFY_TOPIC:-dfrank-claude-$(hostname -s | tr '[:upper:]' '[:lower:]')}"
project=$(basename "${PWD:-unknown}")

label_file="$HOME/.claude/task-labels/${TMUX_PANE}"
if [[ -f "$label_file" ]]; then
  msg=$(cat "$label_file")
elif [[ -n "${TMUX:-}" ]]; then
  msg=$(tmux display-message -t "$TMUX_PANE" -p '#{pane_title}' 2>/dev/null)
fi
msg="${msg:-Input needed}"

curl -s \
  -H "Title: ${project}" \
  -H "Priority: default" \
  -d "$msg" \
  "https://ntfy.sh/${topic}" \
  >/dev/null 2>&1

exit 0
