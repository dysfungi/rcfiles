# shellcheck shell=bash
# sup yarn
# https://yarnpkg.com

yarn_bin_dirs=(
	"$HOME/.yarn/bin"
	"$HOME/.config/yarn/global/node_modules/.bin"
)

for yarn_bin_dir in "${yarn_bin_dirs[@]}"; do
	if [[ -d "$yarn_bin_dir" ]] && [[ ":$PATH:" != *":$yarn_bin_dir:"* ]]; then
		export PATH="$PATH:$yarn_bin_dir"
	fi
done

unset yarn_bin_dirs yarn_bin_dir
