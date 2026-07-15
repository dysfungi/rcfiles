# shellcheck shell=bash
# shellcheck disable=SC2154
autoload colors && colors
# cheers, @ehrenmurdick
# http://github.com/ehrenmurdick/config/blob/master/zsh/prompt.zsh

if command -v git >/dev/null 2>&1; then
	git="$(command -v git)"
else
	git="/usr/bin/git"
fi

git_branch() {
	"$git" symbolic-ref --short HEAD 2>/dev/null
}

git_dirty() {
	if ! "$git" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
		return
	fi

	if [[ -z $("$git" status --porcelain 2>/dev/null) ]]; then
		echo "on %{${fg_bold[green]}%}$(git_prompt_info)%{${reset_color}%}"
	else
		echo "on %{${fg_bold[red]}%}$(git_prompt_info)%{${reset_color}%}"
	fi
}

git_prompt_info() {
	local ref
	ref=$("$git" symbolic-ref HEAD 2>/dev/null) || return
	# echo "(%{\e[0;33m%}${ref#refs/heads/}%{\e[0m%})"
	echo "${ref#refs/heads/}"
}

# This assumes that you always have an origin named `origin`, and that you only
# care about one specific origin. If this is not the case, you might want to use
# `$git cherry -v @{upstream}` instead.
need_push() {
	if ! "$git" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
		return
	fi

	local branch number
	branch=$("$git" symbolic-ref --short HEAD 2>/dev/null) || return
	number=$("$git" cherry -v "origin/$branch" 2>/dev/null | wc -l | tr -d ' ')

	if [[ $number == 0 ]]; then
		echo " "
	else
		echo " with %{${fg_bold[magenta]}%}$number unpushed%{${reset_color}%}"
	fi
}

directory_name() {
	echo "%{${fg_bold[cyan]}%}%1/%\/%{${reset_color}%}"
}

battery_status() {
	if [[ "$(uname -s)" != 'Darwin' ]]; then
		echo "$(date) "
	elif [[ $(sysctl -n hw.model) == *"Book"* ]]; then
		"$DOTFILES"/bin/battery-status
	fi
}

timestamp() {
	echo "%{${fg_bold[green]}%}$(date)%{${reset_color}%}"
}

export PROMPT=$'\n$(timestamp) in $(directory_name) $(git_dirty)$(need_push)\n› '
set_prompt() {
	export RPROMPT="%{${fg_bold[cyan]}%}%{${reset_color}%}"
}

precmd() {
	title "zsh" "%m" "%55<...<%~"
	set_prompt
}
