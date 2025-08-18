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
from _utils import rc


@rc(interactive=False)
def __rc_non_interactive_theme():
    $XONSH_COLOR_STYLE = "default"


@rc(interactive=True)
def __rc_interactive_theme(aliases):
    from xonsh.pyghooks import (
        Token,
        register_custom_pygments_style,
    )
    from xonsh.tools import register_custom_style

    THEME_NAME = "frank"
    THEME_BASE = "dracula" if !(xontrib load dracula) else "inkpot"  # https://github.com/agoose77/xontrib-dracula
    THEME_STYLES = {
        # Token.Color.BLACK: "#444444",
        Token.Color.BLUE: "#0099ff",
        Token.Color.CYAN: "#95a5d7",
        # Token.Color.INTENSE_CYAN: "#f5f5f7",
        # Token.Color.CYAN__BACKGROUND_GREEN: "#ffffff",
        # Token.Color.BACKGROUND_GREEN: "#ffffff",
        Token.Color.INTENSE_BLUE: "#00bbff",
        Token.Color.GREEN: "#008800",
        Token.Color.PURPLE: "#8294c6",
        Token.Color.YELLOW: "#999900",
        # Token.Generic.Output: "#cccccc",
        # Token.PTK.Aborting: "#cccccc",
        Token.PTK.AutoSuggestion: "#ccffcc",
    }

    try:
        register_custom_style(THEME_NAME, THEME_STYLES, base=THEME_BASE)
    except (KeyError, ValueError):
        # TODO(https://github.com/xonsh/xonsh/issues/5163): Use register_custom_style(..., base=THEME_BASE)
        register_custom_pygments_style(THEME_NAME, THEME_STYLES, base=THEME_BASE)

    $XONSH_COLOR_STYLE = THEME_NAME
