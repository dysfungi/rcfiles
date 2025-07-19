import logging
from _utils import rc, threaded

logger = logging.getLogger(__name__)


@rc(interactive=True)
def __rc_interactive_secrets():
    $XONTRIB_1PASSWORD_ENABLED = False
    xontrib load 1password  # https://github.com/drmikecrowe/xontrib-1password

    for secret_file in p"~/.secrets".glob("*"):
        secret_value = $(cat @(secret_file))
        if not secret_value or secret_value.startswith("op://"):
            logger.warning("Failed to load secret from file - %s=%s", secret_file, secret_value)
            continue

        ${secret_file.name} = secret_value

    opurl_by_envname = {
        "CHEZMOI_GITHUB_ACCESS_TOKEN": "op://CLI/GitHub Token - Chezmoi/password",
        "OP_SERVICE_ACCOUNT_TOKEN": "op://CLI/1Password Service Account - CLI - Personal/credential",
    }

    @threaded(event=events.on_post_init)
    def _load_secrets():
        with ${...}.swap(XONTRIB_1PASSWORD_ENABLED=True):
            for env_name, op_url in opurl_by_envname.items():
                current = ${...}.get(env_name)
                if current and not current.startswith("op://"):
                    continue

                secret = str(OnePass(op_url))
                if secret.startswith("op://"):
                    logger.warning("Failed to load secret - %s=%s", env_name, op_url)
                    continue

                ${env_name} = str(secret)
