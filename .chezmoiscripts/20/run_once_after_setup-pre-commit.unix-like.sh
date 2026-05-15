#!/usr/bin/env -S mise exec pre-commit -- bash
# shellcheck shell=bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

cd "${CHEZMOI_SOURCE_DIR}"
pre-commit install

echo >&2 "INFO: Ending $0"
