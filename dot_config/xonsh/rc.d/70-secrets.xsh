from _utils import rc


@rc(interactive=True)
def __rc_interactive_secrets():
    $XONTRIB_1PASSWORD_ENABLED = True

    xontrib load 1password  # https://github.com/drmikecrowe/xontrib-1password
