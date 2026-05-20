from pathlib import Path

from _utils import rc


@.env.setdefault("MANPATH", [])


def _unique_path_prepend(path: Path, *, manpath: bool = False):
    if not path.exists():
        return

    strpath = str(path)
    envpath = $MANPATH if manpath else $PATH
    if strpath in envpath:
        return
    envpath.insert(0, strpath)


def _unique_path_append(path: Path, *, manpath: bool = False):
    if not path.exists():
        return

    strpath = str(path)
    envpath = $MANPATH if manpath else $PATH
    if strpath in envpath:
        return
    envpath.append(strpath)


@rc(login=True)
def __rc_paths_macos():
    if not @.imp.xonsh.platform.ON_DARWIN:
        return

    # https://xon.sh/platform-issues.html#path-helper
    source-bash --seterrprevcmd "" /etc/profile


@rc(login=True)
def __rc_paths_windows():
    if not @.imp.xonsh.platform.ON_WINDOWS:
        return

    # Common Windows paths for Neovim, Git, etc. if not in PATH
    if "ProgramFiles" in ${...}:
        _unique_path_prepend(Path($ProgramFiles) / "Neovim" / "bin")

    # Local bin for user-installed tools (including mise)
    _unique_path_prepend(p"~/.local/bin")


@rc(login=True)
def __rc_paths_common():
    usr_local = p"/usr/local"
    _unique_path_append(usr_local / "sbin")
    _unique_path_append(usr_local / "bin")
    _unique_path_append(usr_local / "share" / "man", manpath=True)


@rc(login=True)
def __rc_paths_homebrew():
    homebrew_prefix = p"/opt/homebrew"
    if not (homebrew_prefix / "bin" / "brew").exists():
        return

    _unique_path_prepend(homebrew_prefix / "sbin")
    _unique_path_prepend(homebrew_prefix / "bin")
    _unique_path_prepend(homebrew_prefix / "share" / "man", manpath=True)


@rc(login=True)
def __rc_paths_mise():
    local_prefix = p"~/.local"
    _unique_path_prepend(local_prefix / "bin")
    _unique_path_append(local_prefix / "share" / "man", manpath=True)
