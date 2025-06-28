#!/usr/bin/env bash
set -euo pipefail

nvim --headless +MasonUpdate +MasonToolsInstallSync +MasonToolsUpdateSync +q
