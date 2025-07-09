from _utils import rc, reset_current_job


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


@rc(interactive=True)
def __rc_interactive(xsh):
    if not $(command -v mise):
        return

    # https://mise.jdx.dev/installing-mise.html#xonsh
    # execx($(/opt/homebrew/bin/mise activate xonsh))
    _activate_mise(xsh)

    # https://mise.jdx.dev/getting-started.html#mise-exec-run
    xsh.aliases["x"] = ["mise", "exec", "--"]

    # https://mise.jdx.dev/getting-started.html#mise-exec-run
    xsh.aliases["xuv"] = "$UV_PYTHON=@(__import__('sys').executable) uv @($args)"
