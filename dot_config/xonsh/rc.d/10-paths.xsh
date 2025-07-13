from pathlib import Path

from _utils import rc


def _unique_path_prepend(path: Path):
    if not path.exists():
        return

    strpath = str(path)
    if strpath in $PATH:
        return

    $PATH.insert(0, strpath)


def _unique_path_append(path: Path):
    if not path.exists():
        return

    strpath = str(path)
    if strpath in $PATH:
        return

    $PATH.append(strpath)


@rc
def __rc_paths_macos():
    # https://xon.sh/platform-issues.html#path-helper
    source-bash --seterrprevcmd "" /etc/profile


@rc
def __rc_paths_common():
    usr_local = p"/usr/local"
    _unique_path_prepend(usr_local / "sbin")
    _unique_path_prepend(usr_local / "bin")


@rc
def __rc_paths_homebrew():
    if !(xontrib load homebrew):  # https://github.com/eugenesvk/xontrib-homebrew
        return

    homebrew_prefix = p"/opt/homebrew"
    _unique_path_prepend(homebrew_prefix / "sbin")
    _unique_path_prepend(homebrew_prefix / "bin")


@rc
def __rc_paths_mise():
    local_bin = p"~/.local/bin"
    _unique_path_append(local_bin)
