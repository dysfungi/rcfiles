from _utils import rc, threaded


@rc(interactive=True)
def __rc_interactive_secrets():
    $XONTRIB_1PASSWORD_ENABLED = True

    xontrib load 1password  # https://github.com/drmikecrowe/xontrib-1password

    @threaded(event=events.on_post_init)
    def _load_secrets():
        if not $XONTRIB_1PASSWORD_ENABLED:
            return "xontrib-1password is disabled"

        result = "success"
        chezmoi_github_token = OnePass("op://Private/GitHub Token - Chezmoi/password")
        try:
            $CHEZMOI_GITHUB_ACCESS_TOKEN
        except KeyError:
            $CHEZMOI_GITHUB_ACCESS_TOKEN = str(chezmoi_github_token)
            if not chezmoi_github_token.active:
                result = "failed"

        return result
