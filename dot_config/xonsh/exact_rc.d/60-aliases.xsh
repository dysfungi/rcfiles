from _utils import rc


@rc(interactive=True)
def __rc_interactive_aliases_xonsh(aliases):
    import pprint

    from xonsh.ansi_colors import ansi_style_by_name
    from xonsh.pyghooks import pygments_style_by_name

    @aliases.register("theme")
    def _show_theme(args: list[str]):
        theme_name = args[0] if args else $XONSH_COLOR_STYLE
        pprint.pprint({
            "ansi": ansi_style_by_name(theme_name),
            "pygments": pygments_style_by_name(theme_name),
        })


@rc(interactive=True)
def __rc_interactive_aliases_mise(aliases):
    # https://mise.jdx.dev/getting-started.html#mise-exec-run
    aliases["x"] = ["mise", "exec", "--"]


@rc(interactive=True)
def __rc_interactive_aliases_uv(aliases):
    import sys

    @aliases.register("xuv")
    def _xonsh_uv(args: list[str]):
        # https://mise.jdx.dev/getting-started.html#mise-exec-run
        # https://github.com/astral-sh/uv/issues/4635#issuecomment-2197754249
        # https://github.com/xonsh/xonsh/issues/5883
        $UV_PYTHON=@(sys.executable) uv @(args)


@rc(interactive=True)
def __rc_interactive_aliases_python(aliases):
    import logging
    from pprint import pprint

    logger = logging.getLogger(__name__)

    @aliases.register("p")
    def _print(args):
        logger.debug("args=%r", args)
        print(*args)

    @aliases.register("pp")
    def _pretty_print(args):
        logger.debug("args=%r", args)
        for arg in args:
            pprint(arg)


@rc(interactive=True)
def __rc_interactive_aliases_builtin(aliases):
    """
    References:
        https://pubs.opengroup.org/onlinepubs/9699919799//utilities/V3_chap02.html#tag_18_09
    """
    from pathlib import Path

    @aliases.register("cv")
    @aliases.return_command
    def _cdargs_cv(args: list[str]):
        cdargs @(args)
        return ["cd", $(cat '$HOME/.cdargsresult')]

    aliases["-"] = aliases["cd-"] = "cd -"

    # https://github.com/anki-code/xontrib-rc-awesome/blob/main/xontrib/rc_awesome.xsh#L126
    @aliases.register(".")
    @aliases.register("cd.")
    @aliases.register("..")
    @aliases.register("cd..")
    @aliases.register("...")  # TODO: fix to override Ellipsis
    @aliases.register("cd...")
    @aliases.register("....")
    @aliases.register("cd....")
    def _alias_cd_dots(*args, **kwargs):
        cd @("../" * len($__ALIAS_NAME.lstrip("cd")))

    aliases["cwd"] = Path.cwd
    aliases["wd"] = lambda: Path.cwd().stem


@rc(interactive=True)
def __rc_interactive_aliases_gnu_coreutils(aliases):
    """
    References:
        https://pubs.opengroup.org/onlinepubs/9699919799//utilities/V3_chap02.html#tag_18_09
    """
    # https://xon.sh/xonshrc.html#get-better-colors-from-the-ls-command
    # $LS_COLORS='rs=0:di=01;36:ln=01;36:mh=00:pi=40;33:so=01;35:do=01;35:bd=40;33;01:cd=40;33;01:or=40;31;01:su=37;41:sg=30;43:ca=30;41:tw=30;42:ow=34;42:st=37;44:ex=01;32:'

    if !(command -v gls >/dev/null):
        aliases["ls"] = ["gls", "--color=auto"]
    elif !(ls --color):
        aliases["ls"] = ["gls", "--color=auto"]
    else:
        aliases["ls"] = ["ls", "-A"]

    aliases["l"] = ["ls", "-CFAL"]
    aliases["l1"] = ["ls", "-A1"]
    aliases["la"] = ["ls", "-A"]
    aliases["la1"] = ["l1"]
    aliases["ll"] = ["ls", "-alFh"]

    @aliases.register("touchp")
    def _touch_with_parents(args):
        for file in map(Path, args):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.touch(exist_ok=True)


@rc(interactive=True)
def __rc_interactive_aliases_gnu_moreutils(aliases):
    if !(command -v gsed >/dev/null):
        aliases["sed"] = ["gsed"]


@rc(interactive=True)
def __rc_interactive_aliases_written_in_rust(aliases):
    aliases["rp"] = aliases["rpar"] = aliases["rparallel"] = "rust-parallel"


@rc(interactive=True)
def __rc_interactive_aliases_tmux(aliases):

    @aliases.register("tmx")
    @aliases.register("tmu")
    def _tmux(args: list[str]):
        tmux attach -t @(args) || tmux new -s @(args)


@rc(interactive=True)
def __rc_interactive_aliases_neovim(aliases):
    if not !(command -v nvim >/dev/null):
        return

    aliases["vi"] = aliases["vim"] = "nvim"


@rc(interactive=True)
def __rc_interactive_aliases_chezmoi(aliases):

    @aliases.register("chez")
    @aliases.return_command
    def _chez(args: list[str]):
        return ["chezmoi", *args]

    aliases["chezad"] = "chez add"
    aliases["chezap"] = "chez apply"
    aliases["chezd"] = "chez diff"

    @aliases.register("chezrun")
    @aliases.return_command
    def _chezrun(args: list[str]):
        script = $(chez execute-template --file @(args))
        return ["sh", "-c", script]


@rc(interactive=True)
def __rc_interactive_aliases_ai(aliases):
    aliases["ai"] = aliases["fabric"] = "fabric-ai"

    for pattern in $(fabric-ai --listpatterns).splitlines():
        aliases[pattern] = ["fabric-ai", f"--pattern={pattern}"]

    aliases["ai-patterns"] = aliases["aipatterns"] = aliases["patterns"] = [
        "fzf",
        "--preview=cat {}",
        "--walker-root=$HOME/.config/fabric/patterns",
        # "--preview-window=up:50%:wrap",
    ]
    aliases["ai-strategies"] = aliases["aistrategies"] = aliases["strategies"] = [
        "fzf",
        "--preview=cat {}",
        "--walker-root=$HOME/.config/fabric/strategies",
    ]


@rc(interactive=True)
def __rc_interactive_aliases_web_browser(aliases):
    import urllib.parse
    import webbrowser

    # https://xon.sh/tutorial.html#callable-aliases
    aliases["web"] = aliases["webw"] = lambda args: webbrowser.open(*args)
    aliases["webn"] = lambda args: webbrowser.open_new(*args)
    aliases["webt"] = lambda args: webbrowser.open_new_tab(*args)

    def _search(base_url: str, string_args: list[str], *, query_varname: str = "q"):
        query_varvalue = '+'.join(map(urllib.parse.quote, string_args))
        url = f"{base_url}?{query_varname}={query_varvalue}"
        print(f"Opening {url} in the browser...")
        webbrowser.open(url)

    @aliases.register("ddg")
    @aliases.register("duckduckgo")
    def _duckduckgo(args: list[str], **kwargs):
        _search("https://duckduckgo.com/", args)

    @aliases.register("google")
    def _google(args: list[str], **kwargs):
        _search("https://google.com/search", args)


    @aliases.register("kagi")
    def _kagi(args: list[str], **kwargs):
        _search("https://kagi.com/search", args)

    # Default
    aliases["search"] = "kagi"
    aliases["s"] = "search"

    # Refined
    @aliases.register("pypi")
    @aliases.return_command
    def _search_bang(args: list[str]):
        return ["search", "!pypi", *args]

    @aliases.register("py3")
    @aliases.return_command
    def _search_bang(args: list[str]):
        return ["search", "!py3", *args]

    @aliases.register("py2")
    @aliases.return_command
    def _search_bang(args: list[str]):
        return ["search", "!py2", *args]


@rc(interactive=True)
def __rc_interactive_aliases_fun(aliases):
    aliases["starwars"] = ["telnet", "towel.blinkenlights.nl"]

    aliases["sitenamr"] = r"grep '^[a-z].*[^aeiou]er$' /usr/share/dict/words | shuf -n 1 | sed -r -e 's/er$/r/' -e r's/^(\w)/\1/'"
    aliases["sitenamd"] = r"grep '^[a-z].*[^aeiou]ed$' /usr/share/dict/words | shuf -n 1 | sed -r -e 's/ed$/d/' -e r's/^(\w)/\1/'"


@rc(interactive=True)
def __rc_interactive_aliases_miscellaneous(aliases):
    import requests

    @aliases.register
    @aliases.return_command
    def _caff(args):
        hours = int(args[0]) if args else 8
        hours_in_minutes = hours * 60 * 60
        print(f"Caffeinating for {hours} hour(s)...")
        return ["caffeinate", "-t", str(hours_in_minutes)]

    @aliases.register("eip")
    def _external_ip(args):
        response = requests.get("https://icanhazip.com")
        print(response.text.strip())

    aliases["iip"] = "/sbin/ifconfig | awk '/inet / { print $2; }' | grep -Fv 127.0.0.1"

    @aliases.register("aip")
    def _all_ip(args):
        internal = $(iip)
        external = $(eip)
        print(f"External IP:\n{external}\n\nInternal IP:\n{internal}")
