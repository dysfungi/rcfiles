# login(1)-style startup notice for fresh zsh shells NOT spawned via login(1)
# (WezTerm launch-menu zsh, ssh, bare `zsh`): zsh's native MAILCHECK only
# announces mail that arrives AFTER startup, never a pre-existing spool.
[[ -s $MAIL ]] && print -u2 "You have mail."
