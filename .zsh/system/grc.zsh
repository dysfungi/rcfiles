# shellcheck shell=bash
# GRC colorizes nifty unix tools all over the place
if command -v grc >/dev/null 2>&1 && command -v brew >/dev/null 2>&1; then
	# shellcheck disable=SC1091
	source "$(brew --prefix)/etc/grc.zsh"
fi
