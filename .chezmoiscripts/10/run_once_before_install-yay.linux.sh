#!/usr/bin/env bash
# Bootstrap the yay AUR helper on Arch Linux.
# Idempotent — exits immediately if yay is already installed.

set -euo pipefail

echo >&2 "INFO: Starting $0"

if command -v yay >/dev/null 2>&1; then
  echo >&2 "INFO: yay already installed; skipping."
  echo >&2 "INFO: Ending $0"
  exit 0
fi

if ! command -v pacman >/dev/null 2>&1; then
  echo >&2 "WARNING: pacman not found; skipping yay install."
  echo >&2 "INFO: Ending $0"
  exit 0
fi

echo >&2 "INFO: Installing yay AUR helper..."
sudo pacman -Syu --noconfirm --needed base-devel git

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

git clone https://aur.archlinux.org/yay.git "${tmpdir}/yay"
(cd "${tmpdir}/yay" && makepkg -si --noconfirm)

echo >&2 "INFO: yay installed successfully."
echo >&2 "INFO: Ending $0"
