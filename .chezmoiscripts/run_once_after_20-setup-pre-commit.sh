#!/usr/bin/env -S mise exec pre-commit -- bash
# shellcheck shell=bash
set -euo pipefail

cd "${CHEZMOI_SOURCE_DIR}"
pre-commit install
