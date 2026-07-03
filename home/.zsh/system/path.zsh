# Keep $PATH entries unique (mise's _.path prepends can leave a duplicate that
# path_helper preserved); zsh auto-dedups this array on every mutation, keep-first.
typeset -U path PATH

export PATH="/usr/local/bin:/usr/local/sbin:$PATH"
export MANPATH="/usr/local/man:/usr/local/git/man:$MANPATH"
