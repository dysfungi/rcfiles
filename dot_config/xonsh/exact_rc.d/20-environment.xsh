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
    $CHEZMOI_SOURCE_DIR = $(chezmoi source-path)
    $CHEZMOI_WORKING_TREE = $(chezmoi data --format=json | jq --raw-output '.chezmoi.workingTree')
