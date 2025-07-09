import urllib.parse

from _utils import rc


@rc(interactive=True)
def __rc_interactive(xsh):
    # Engines
    xsh.aliases["google"] = "web @('https://google.com/search?q=' + '+'.join(map(urllib.parse.quote, $args)))"
    xsh.aliases["duckduckgo"] = "web @('https://duckduckgo.com/?q=' + '+'.join(map(urllib.parse.quote, $args)))"
    xsh.aliases["ddg"] = "duckduckgo"
    xsh.aliases["kagi"] = "web @('https://kagi.com/search?q=' + '+'.join(map(urllib.parse.quote, $args)))"
    # Default
    xsh.aliases["search"] = "kagi"
    xsh.aliases["s"] = "search"
    # Refined
    xsh.aliases["pypi"] = "search '!pypi' @($args)"
    xsh.aliases["py3"] = "search '!py3' @($args)"
    xsh.aliases["py2"] = "search '!py2' @($args)"
