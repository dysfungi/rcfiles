#!/usr/bin/env bash
# Stop hook: send ntfy.sh notification when away mode is active (~/.claude/away sentinel).
[[ ! -f "$HOME/.claude/away" ]] && exit 0

topic="${NTFY_TOPIC:-dfrank-claude-$(hostname -s | tr '[:upper:]' '[:lower:]')}"
project=$(basename "${PWD:-unknown}")

if [[ -n "${TMUX:-}" ]]; then
  pane_title=$(tmux display-message -p '#{pane_title}' 2>/dev/null)
  session=$(tmux display-message -p '#S' 2>/dev/null)
fi

title="${session:+[$session] }${project}"
msg="${pane_title:-Input needed}"

curl -s \
  -H "Title: ${title}" \
  -H "Priority: default" \
  -d "$msg" \
  "https://ntfy.sh/${topic}" \
  >/dev/null 2>&1

exit 0
