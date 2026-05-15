#!/usr/bin/env -S mise exec pre-commit -- bash
# shellcheck shell=bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

cd "${CHEZMOI_SOURCE_DIR}"

if git config --get core.hooksPath >/dev/null 2>&1; then
  echo >&2 "WARN: Unsetting repo-local core.hooksPath for pre-commit compatibility"
  git config --unset core.hooksPath
fi

pre-commit install

echo >&2 "INFO: Ending $0"
