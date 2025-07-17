from _utils import rc, reset_current_job


@rc(interactive=True)
def __rc_interactive_env_essential(xsh):
    xsh.env.setdefault("EDITOR", "nvim -e")
    xsh.env.setdefault("VISUAL", "nvim")


def _activate_mise(xsh):
    import subprocess
    from os import environ

    xsh.env['MISE_SHELL'] = 'xonsh'
    xsh.env['MISE_SHELL'] = xsh.env.get_detyped('MISE_SHELL')

    @events.on_pre_prompt
    def _mise_activate_hook(*args, **kwargs):
        hook = $(command mise hook-env -s xonsh)
        if hook:
            execx(hook)
        reset_current_job()

    def _mise(args):
        if args and args[0] in ('deactivate', 'shell', 'sh'):
            return execx($(command mise @(args)))
        else:
            return $(command mise @(args))

    xsh.aliases['mise'] = _mise


@rc
def __rc_env_mise(xsh):
    if !(xontrib load mise):  # https://github.com/eugenesvk/xontrib-mise
        return

    # https://mise.jdx.dev/installing-mise.html#xonsh
    # execx($(/opt/homebrew/bin/mise activate xonsh))
    _activate_mise(xsh)


@rc(interactive=True)
def __rc_env_chezmoi():
    import json

    data = json.loads($(chezmoi data --format=json))
    data_chezmoi = data["chezmoi"]

    $CHEZMOI_SOURCE_DIR = data_chezmoi["sourceDir"]
    $CHEZMOI_WORKING_TREE = data_chezmoi["workingTree"]

    $IS_MY_MACHINE = data["isMyMachine"]
    $IS_WORK_MACHINE = data["isWorkMachine"]
    $IS_RIOT_MACHINE = data["isRiotMachine"]


@rc(interactive=True)
def __rc_env_riot():
    if not $IS_RIOT_MACHINE:
        return

    # AWS
    $AWS_PROFILE = "product-services"

    # Gandalf
    $GANDALF_ENABLE_AUTOUPGRADE = 1

    # Go
    $GO111MODULE = "on"
    $GOPRIVATE = "*.riotgames.com"

    # P4/Perforce & LCU
    p4_root_dir = p"/Users/Shared/p4"
    p4_depot_dir = p4_root_dir / "depot"
    p4_lol_dir = p4_depot_dir / "LoL"
    p4_lol_main_dir = p4_lol_dir / "__MAIN__"
    p4_lol_code_dir = p4_lol_main_dir / "code"
    $P4CONFIG = p4_lol_code_dir / "RiotClient" / "DevTools" / "VSCodeWorkspace" / ".p4config"

    # Vault
    $VAULT_ADDR = "https://vault.security.riotgames.io"
