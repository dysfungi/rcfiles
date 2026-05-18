#!/bin/bash
set -euo pipefail

LOCAL="$CLAUDE_PROJECT_DIR/.claude/settings.local.json"
SETTINGS="$CLAUDE_PROJECT_DIR/.claude/settings.json"

if [[ ! -f "$LOCAL" ]] || ! jq -e '.permissions.allow | length > 0' "$LOCAL" >/dev/null 2>&1; then
  exit 0
fi

tmp="$(mktemp)"
jq -s '
  (.[0].permissions.allow // []) as $existing |
  (.[1].permissions.allow // []) as $new |
  .[0] | .permissions.allow = ($existing + $new | unique)
' "$SETTINGS" "$LOCAL" >"$tmp"
mv "$tmp" "$SETTINGS"

jq 'del(.permissions)' "$LOCAL" >"$tmp"
mv "$tmp" "$LOCAL"
