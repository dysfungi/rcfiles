#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

if ! command -v opam >/dev/null 2>&1; then
  echo >&2 "WARNING: opam not installed; skipping."
  echo >&2 "INFO: Ending $0"
  exit 0
fi

opam init --no-setup

echo >&2 "INFO: Ending $0"
