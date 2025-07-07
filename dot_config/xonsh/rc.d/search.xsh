import urllib.parse

from xonsh.built_ins import XSH


def _rc_search():
    _alias_search()


def _alias_search():
    # Engines
    XSH.aliases["google"] = "web @('https://google.com/search?q=' + '+'.join(map(urllib.parse.quote, $args)))"
    XSH.aliases["duckduckgo"] = "web @('https://duckduckgo.com/?q=' + '+'.join(map(urllib.parse.quote, $args)))"
    XSH.aliases["ddg"] = "duckduckgo"
    XSH.aliases["kagi"] = "web @('https://kagi.com/search?q=' + '+'.join(map(urllib.parse.quote, $args)))"
    # Default
    XSH.aliases["search"] = "kagi"
    XSH.aliases["s"] = "search"
    # Refined
    XSH.aliases["pypi"] = "search '!pypi' @($args)"
    XSH.aliases["py3"] = "search '!py3' @($args)"
    XSH.aliases["py2"] = "search '!py2' @($args)"


if $XONSH_INTERACTIVE:
    _rc_search()
