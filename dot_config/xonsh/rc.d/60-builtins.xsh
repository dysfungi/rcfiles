"""
References:
    https://pubs.opengroup.org/onlinepubs/9699919799//utilities/V3_chap02.html#tag_18_09
"""
from pathlib import Path
from _utils import rc


@rc(interactive=True)
def __rc_interactive_cd(xsh):

    xsh.aliases["cv"] = 'cdargs @($args) && cd $(cat "$HOME/.cdargsresult")'

    xsh.aliases["-"] = "cd -"
    xsh.aliases["cd-"] = "cd -"

    # https://github.com/anki-code/xontrib-rc-awesome/blob/main/xontrib/rc_awesome.xsh#L126
    @xsh.aliases.register(".")
    @xsh.aliases.register("cd.")
    @xsh.aliases.register("..")
    @xsh.aliases.register("cd..")
    @xsh.aliases.register("...")  # TODO: fix to override Ellipsis
    @xsh.aliases.register("cd...")
    @xsh.aliases.register("....")
    @xsh.aliases.register("cd....")
    def _alias_cd_dots(*args, **kwargs):
        cd @("../" * len($__ALIAS_NAME.lstrip("cd")))


@rc(interactive=True)
def __rc_interactive_pwd(xsh):
    xsh.aliases["cwd"] = Path.cwd
    xsh.aliases["wd"] = lambda: Path.cwd().stem
