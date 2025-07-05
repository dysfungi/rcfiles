"""
Dark themes I like:
    dracula
    inkpot
    ---
    fruity
    github-dark
    monokai
    native
    vim

To preview the themes, run:

    xonfig web

References:
    https://xon.sh/customization.html#customizing-xonsh-how-do-i
    https://xon.sh/xonshrc.html#xonfig-web
"""
from xonsh.built_ins import XSH
from xonsh.tools import register_custom_style
from xonsh.pyghooks import (
    Token,
    # pygments_style_by_name,
    register_custom_pygments_style,
)


def _rc_theme():
    THEME_NAME = "frank"
    THEME_BASE = "dracula"
    THEME_STYLES = {
        # Token.Color.BLACK: "#008800",
        Token.Color.BLUE: "#00aaff",
        # Token.Color.BOLD_BLUE: "#008800",
        # Token.Color.BOLD_GREEN: "#008800",
        # Token.Color.GREEN: "#008800",
        # Token.Color.INTENSE_BLACK: "#008800",
        # Token.Generic.Output: "#008800",
        # Token.PTK.Aborting: "#008800",
        Token.PTK.AutoSuggestion: "#ccffcc",
    }

    try:
        # TODO(https://github.com/xonsh/xonsh/issues/5163): Use register_custom_style(..., base=THEME_BASE)
        register_custom_style(THEME_NAME, THEME_STYLES, base=THEME_BASE)
    except (KeyError, ValueError):
        register_custom_pygments_style(THEME_NAME, THEME_STYLES, base=THEME_BASE)

    $XONSH_COLOR_STYLE = THEME_NAME


if $XONSH_INTERACTIVE:
    _rc_theme()
