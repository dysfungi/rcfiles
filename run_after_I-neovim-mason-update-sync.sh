#!/usr/bin/env bash
set -euo pipefail

nvim --headless +MasonUpdate +MasonToolsClean +MasonToolsInstallSync +MasonToolsUpdateSync +q
