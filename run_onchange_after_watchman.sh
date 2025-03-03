#!/usr/bin/env bash
set -euo pipefail

watchman watch-project "$HOME/.config/homebrew/dump"
watchman --json-command <<-EOT
  [ "trigger"
  , "$HOME/.config/homebrew/dump"
  , { "name": "chezmoi-add-homebrew-dumps"
    , "expression": ["match", "Brewfile.*"]
    , "command": ["chezmoi", "add"]
    , "append_files": true
    }
  ]
EOT
