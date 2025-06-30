from xonsh.built_ins import XSH


def _rc_mise():
    _auto_activate_mise()
    _alias_mise()


def _auto_activate_mise():
    if not $(command -v mise):
        return

    # https://mise.jdx.dev/installing-mise.html#xonsh
    execx($(mise activate xonsh))


def _alias_mise():
    # https://mise.jdx.dev/getting-started.html#mise-exec-run
    XSH.aliases["x"] = ["mise", "exec", "--"]


if $XONSH_INTERACTIVE:
    _rc_mise()
