from xonsh.built_ins import XSH
from _utils import reset_current_job


def _rc_mise():
    _auto_activate_mise()
    _alias_mise()


def _auto_activate_mise():
    if not $(command -v mise):
        return

    # https://mise.jdx.dev/installing-mise.html#xonsh
    # execx($(/opt/homebrew/bin/mise activate xonsh))

    from os               import environ
    import subprocess
    from xonsh.built_ins  import XSH

    envx = XSH.env
    envx[   'MISE_SHELL'] = 'xonsh'
    environ['MISE_SHELL'] = envx.get_detyped('MISE_SHELL')

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

    XSH.aliases['mise'] = _mise


def _alias_mise():
    # https://mise.jdx.dev/getting-started.html#mise-exec-run
    XSH.aliases["x"] = ["mise", "exec", "--"]


if $XONSH_INTERACTIVE:
    _rc_mise()
