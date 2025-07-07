import urllib.parse

from xonsh.built_ins import XSH


def _rc_search():
    _alias_search()


def _alias_search():
    XSH.aliases["search"] = "web @('https://kagi.com/search?q=' + '+'.join(map(urllib.parse.quote, $args)))"
    XSH.aliases["s"] = "search"
    XSH.aliases["pypi"] = "search '!pypi' @($args)"
    XSH.aliases["py3"] = "search '!py3' @($args)"
    XSH.aliases["py2"] = "search '!py2' @($args)"


if $XONSH_INTERACTIVE:
    _rc_search()
