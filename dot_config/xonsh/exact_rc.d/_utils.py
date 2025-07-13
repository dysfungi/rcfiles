import functools
import inspect
from typing import Any, Callable, Optional

from xonsh.built_ins import XSH


def rc(
    func: Optional[Callable[..., Any]] = None,
    *,
    autorun: bool = True,
    interactive: Optional[bool] = None,
    login: Optional[bool] = None,
):
    """Decorator to wrap functions in RC files. Auto-runs wrapped
    functions by default and can specify if the function should only
    be run in interactive or login shells.

    If ``interactive`` is not set, then it will be set to ``True`` if
    "interactive" is in the function name and ``False`` if
    "non_interactive" is in the function name.

    If ``login`` is not set, then it will be set to ``True`` if
    "login" is in the function name and ``False`` if
    "non_login" is in the function name.
    """

    def decorator(func: Callable[..., Any], *, _interactive=interactive, _login=login):
        if _interactive is None:
            match func.__name__:
                case x if "non_interactive" in x:
                    _interactive = False
                case x if "interactive" in x:
                    _interactive = True

        if _login is None:
            match func.__name__:
                case x if "non_login" in x:
                    _login = False
                case x if "login" in x:
                    _login = True

        sig = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if interactive is not None and XSH.env["XONSH_INTERACTIVE"] != _interactive:
                return

            if login is not None and XSH.env["XONSH_LOGIN"] != _login:
                return

            if "aliases" in sig.parameters:
                kwargs["aliases"] = XSH.aliases

            if "xession" in sig.parameters:
                kwargs["xession"] = XSH

            if "xsh" in sig.parameters:
                kwargs["xsh"] = XSH

            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            return func(*bound_args.args, **bound_args.kwargs)

        if autorun:
            wrapper()

        return wrapper

    return decorator if func is None else decorator(func)


def reset_current_job():
    if not XSH.shell:
        return

    prompt_fields = XSH.env["PROMPT_FIELDS"]
    with prompt_fields["current_job"].update_current_cmds([["xonsh"]]):
        prompt_fields.reset_key("current_job")
        XSH.shell.settitle()
