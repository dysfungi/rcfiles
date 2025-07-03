from xonsh.built_ins import XSH


def _rc_chezmoi():
    XSH.aliases["chez"] = "chezmoi"
    XSH.aliases["chezad"] = "chezmoi add"
    XSH.aliases["chezap"] = "chezmoi apply"
    XSH.aliases["chezd"] = "chezmoi diff"


if $XONSH_INTERACTIVE:
    _rc_chezmoi()
