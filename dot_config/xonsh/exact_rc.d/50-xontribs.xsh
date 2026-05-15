from _utils import rc


@rc(interactive=True)
def __rc_interactive_load_xontribs():
    $XONTRIBS_AUTOLOAD_DISABLED = True

    # https://github.com/drmikecrowe/xontrib-1password#disabling
    # NOTE(https://github.com/xonsh/xonsh/issues/5872): $XONTRIBS_AUTOLOAD_DISABLED is not respected
    # Do NOT set $XONTRIBS_AUTOLOAD_DISABLED = False here — enabling autoload lets coconut
    # autoload via its entry point and patch xonsh's source transformer before we can stop it.
    # Coconut's implicit partial syntax (`.attr`) transforms dot-prefixed hidden file args
    # (e.g. `.mise.toml` → `.mise`), stripping the last extension in subprocess commands.
    # Instead, rely on explicit xontrib loading only.
    # xontrib load coconut  # https://github.com/evhub/coconut

    xontrib load coreutils  # https://github.com/xonsh/xontrib-coreutils
    if not @.imp.xonsh.platform.ON_WINDOWS:
        xontrib load term_integration  # https://github.com/jnoortheen/xontrib-term-integrations#usage


@rc(interactive=False)
def __rc_non_interactive_disable_xontribs():
    $XONTRIBS_AUTOLOAD_DISABLED = True
