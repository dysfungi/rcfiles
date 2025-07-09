from _utils import rc


@rc(interactive=True)
def __rc_interactive():
    # https://github.com/drmikecrowe/xontrib-1password#disabling
    # NOTE(https://github.com/xonsh/xonsh/issues/5872): $XONTRIBS_AUTOLOAD_DISABLED is not respected
    $XONTRIBS_AUTOLOAD_DISABLED = False

    xontrib load 1password  # https://github.com/drmikecrowe/xontrib-1password
    xontrib load coconut  # https://github.com/evhub/coconut
    xontrib load coreutils  # https://github.com/xonsh/xontrib-coreutils
    xontrib load dracula  # https://github.com/agoose77/xontrib-dracula
    xontrib load term_integration  # https://github.com/jnoortheen/xontrib-term-integrations#usage


@rc(interactive=False)
def __rc_non_interactive():
    $XONTRIBS_AUTOLOAD_DISABLED = True
