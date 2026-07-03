from _utils import rc


@rc(login=True)
def __rc_paths_macos():
    if not @.imp.xonsh.platform.ON_DARWIN:
        return

    # Load macOS OS-base paths (GNU gnubin farm, dotnet, cryptexes) from /etc/paths.d via
    # path_helper. It reorders $PATH and preserves inherited entries; mise `_.path` re-prepends
    # the managed front-paths each prompt and the mise-hook dedup (20-environment.xsh) removes
    # the duplicate copy path_helper leaves behind.
    source-bash --seterrprevcmd "" /etc/profile
