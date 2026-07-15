# shellcheck shell=bash
_cdargs_sh=/usr/share/cdargs/cdargs-bash.sh
if [[ ! -f "$_cdargs_sh" ]] && command -v brew &>/dev/null; then
	_cdargs_sh="$(brew --prefix)/share/cdargs/cdargs-bash.sh"
fi
# shellcheck source=/dev/null
[[ -f "$_cdargs_sh" ]] && source "$_cdargs_sh"
unset _cdargs_sh
