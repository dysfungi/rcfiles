from _utils import rc


@rc(interactive=True)
def __rc_interactive_load_xontribs():
    # https://github.com/drmikecrowe/xontrib-1password#disabling
    # NOTE(https://github.com/xonsh/xonsh/issues/5872): $XONTRIBS_AUTOLOAD_DISABLED is not respected
    $XONTRIBS_AUTOLOAD_DISABLED = False

    xontrib load coconut  # https://github.com/evhub/coconut
    xontrib load coreutils  # https://github.com/xonsh/xontrib-coreutils
    xontrib load term_integration  # https://github.com/jnoortheen/xontrib-term-integrations#usage


@rc(interactive=False)
def __rc_non_interactive_disable_xontribs():
    $XONTRIBS_AUTOLOAD_DISABLED = True
