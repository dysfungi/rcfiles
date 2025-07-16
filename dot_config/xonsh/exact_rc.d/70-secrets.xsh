from _utils import rc, threaded


@rc(interactive=True)
def __rc_interactive_secrets():
    $XONTRIB_1PASSWORD_ENABLED = False
    xontrib load 1password  # https://github.com/drmikecrowe/xontrib-1password

    $OP_SERVICE_ACCOUNT_TOKEN = $(cat ~/.secrets/OP_SERVICE_ACCOUNT_TOKEN)

    @threaded(event=events.on_post_init)
    def _load_secrets():
        with ${...}.swap(XONTRIB_1PASSWORD_ENABLED=True):
            result = "success"
            chezmoi_github_token = OnePass("op://CLI/GitHub Token - Chezmoi/password")
            try:
                $CHEZMOI_GITHUB_ACCESS_TOKEN
            except KeyError:
                $CHEZMOI_GITHUB_ACCESS_TOKEN = str(chezmoi_github_token)
                if not chezmoi_github_token.active:
                    result = "failed"

            $XONTRIB_1PASSWORD_ENABLED = False
            return result
