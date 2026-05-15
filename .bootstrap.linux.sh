#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

distro="${1:?FATAL: distro ID not passed as argument (expected from chezmoi hook)}"

case "${distro}" in
  arch)
    # 1Password CLI: add official Arch repo
    # https://support.1password.com/install-linux/#arch-linux
    if ! pacman -Qi 1password-cli &>/dev/null; then
      sudo bash -c '
        curl -sS https://downloads.1password.com/linux/keys/1password.asc | pacman-key --add -
        pacman-key --lsign-key 3FEF9748469ADBE15DA7CA80AC2D62742012EA22
        echo -e "[1password]\nSigLevel = TrustAll\nServer = https://downloads.1password.com/linux/arch/aarch64" >> /etc/pacman.conf
      '
    fi

    sudo pacman -Syu --noconfirm --needed git 1password-cli
    ;;
  *)
    echo >&2 "FATAL: Unsupported Linux distribution: ${distro}"
    echo >&2 "Only Arch Linux is supported. Add support in .bootstrap.linux.sh"
    exit 1
    ;;
esac

echo >&2 "INFO: Ending $0"
