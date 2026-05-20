#!/usr/bin/env bash
set -euo pipefail

distro="${1:?FATAL: distro ID not passed as argument (expected from chezmoi hook)}"

case "${distro}" in
arch)
  # Fast-path: skip logging and installs if all bootstrap deps are present
  if command -v op >/dev/null 2>&1 &&
    command -v git >/dev/null 2>&1 &&
    command -v unzip >/dev/null 2>&1 &&
    command -v curl >/dev/null 2>&1; then
    exit 0
  fi

  echo >&2 "INFO: Starting $0"
  sudo pacman -Syu --noconfirm --needed git unzip curl

  if ! command -v op >/dev/null 2>&1; then
    arch=amd64
    case $(uname -m) in aarch64) arch=arm64 ;; esac
    ver=$(curl -s https://app-updates.agilebits.com/check/1/0/CLI2/en/2.0.0/N | sed 's/.*"version":"\([0-9.]*\)".*/\1/')
    url="https://cache.agilebits.com/dist/1P/op2/pkg/v${ver}/op_linux_${arch}_v${ver}.zip"
    curl -sSfo /tmp/op.zip "${url}"
    sudo unzip -o /tmp/op.zip op -d /usr/local/bin
    sudo chmod +x /usr/local/bin/op
    rm /tmp/op.zip
    echo >&2 "INFO: Installed op v${ver} (${arch})"
  fi

  echo >&2 "INFO: Ending $0"
  ;;
*)
  echo >&2 "FATAL: Unsupported Linux distribution: ${distro}"
  echo >&2 "Only Arch Linux is supported. Add support in .bootstrap.linux.sh"
  exit 1
  ;;
esac
