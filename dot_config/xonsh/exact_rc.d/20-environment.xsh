import sys

from _utils import rc, reset_current_job


@rc(interactive=True)
def __rc_interactive_env_essential(xsh):
    xsh.env.setdefault("EDITOR", "nvim -e")
    xsh.env.setdefault("LESS", "-R")
    xsh.env.setdefault("VISUAL", "nvim")
    xsh.env.setdefault("SHELL", next((arg for arg in sys.argv if "xonsh" in arg), "xonsh"))


def _activate_mise(xsh):
    import shutil
    xsh.env.setdefault("MISE_SHELL", "xonsh")
    _mise_bin = shutil.which("mise") or "mise"

    @events.on_pre_prompt
    def _mise_activate_hook(*args, **kwargs):
        hook = $(@(_mise_bin) hook-env -s xonsh)
        if hook:
            execx(hook)
        reset_current_job()

    def _mise(args):
        if args and args[0] in ('deactivate', 'shell', 'sh'):
            return execx($(@(_mise_bin) @(args)))
        # Use ![...] not $[...]: $[] raises CalledProcessError on non-zero exit;
        # FuncAliases run on a ProcProxyThread, so uncaught exceptions surface as
        # "Exception in thread" noise rather than setting $?. ![] never raises —
        # return the int exit code so xonsh sets $? correctly.
        return ![@(_mise_bin) @(args)].returncode

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

    try:
        data = json.loads($(chezmoi data --format=json))
    except Exception as e:
        print(f"warning: chezmoi data failed: {e}", file=sys.stderr)
        return

    data_chezmoi = data["chezmoi"]

    $CHEZMOI_SOURCE_DIR = data_chezmoi["sourceDir"]
    $CHEZMOI_WORKING_TREE = data_chezmoi["workingTree"]

    $IS_MY_MACHINE = data["isMyMachine"]
    $IS_WORK_MACHINE = data["isWorkMachine"]
    $IS_RIOT_MACHINE = data["isRiotMachine"]


@rc(interactive=True)
def __rc_env_riot():
    if not ${...}.get("IS_RIOT_MACHINE", False):
        return

    # AWS
    $AWS_PROFILE = "product-services"

    # Gandalf
    $GANDALF_ENABLE_AUTOUPGRADE = 1

    # Go
    $GO111MODULE = "on"
    $GOPRIVATE = "*.riotgames.com"

    # P4/Perforce — config file name for auto-discovery; macOS uses an absolute path
    if @.imp.xonsh.platform.ON_DARWIN:
        p4_root_dir = p"/Users/Shared/p4"
        p4_depot_dir = p4_root_dir / "depot"
        p4_lol_dir = p4_depot_dir / "LoL"
        p4_lol_main_dir = p4_lol_dir / "__MAIN__"
        p4_lol_code_dir = p4_lol_main_dir / "code"
        $P4CONFIG = p4_lol_code_dir / "RiotClient" / "DevTools" / "VSCodeWorkspace" / ".p4config"
    elif @.imp.xonsh.platform.ON_LINUX:
        $P4CONFIG = ".p4config.wsl"
    else:
        $P4CONFIG = ".p4config"

    # Vault
    $VAULT_ADDR = "https://vault.security.riotgames.io"
