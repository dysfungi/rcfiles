import functools
import inspect
import threading
from typing import Any, Callable, Optional

from xonsh.built_ins import XSH


def rc(
    func: Optional[Callable[..., Any]] = None,
    *,
    autorun: bool = True,
    interactive: Optional[bool] = None,
    login: Optional[bool] = None,
) -> Callable[..., Any]:
    """Decorator to wrap functions in RC files. Auto-runs wrapped
    functions by default and can specify if the function should only
    be run in interactive or login shells.

    The following arg names will be auto-set:

        aliases: __xonsh__.aliases
        env: __xonsh__.env
        imp: __xonsh__.imp
        xession: __xonsh__
        xsh: __xonsh__

    """

    def decorator(
        func: Callable[..., Any],
        *,
        _interactive=interactive,
        _login=login,
    ) -> Callable[..., Any]:
        sig = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            if interactive is not None and XSH.env["XONSH_INTERACTIVE"] != _interactive:
                return

            if login is not None and XSH.env["XONSH_LOGIN"] != _login:
                return

            kwargs.update(
                (name, value)
                for name, value in {
                    "aliases": XSH.aliases,
                    "env": XSH.env,
                    "imp": XSH.imp,
                    "xession": XSH,
                    "xsh": XSH,
                }.items()
                if name in sig.parameters
            )

            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            return func(*bound_args.args, **bound_args.kwargs)

        if autorun:
            wrapper()

        return wrapper

    return decorator if func is None else decorator(func)


def threaded(
    *,
    event: Callable[..., Any],
    attribute: str = "thread",
    bottom_toolbar_result: bool = True,
) -> Callable[..., Any]:
    """Decorator to add a thread instance as an attribute on the decorated function."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                func(*args, **kwargs)
            except Exception as exc:
                if bottom_toolbar_result:
                    threaded.results.append(
                        f"{{RED}}{event.__class__.__name__}({func.__name__}={exc})"
                    )
                raise
            else:
                if bottom_toolbar_result:
                    threaded.results.append(
                        f"{{GREEN}}{event.__class__.__name__}({func.__name__}=OK)"
                    )

        @event
        def _threaded_event_handler(*args, **kwargs):
            thread = threading.Thread(target=wrapper, args=args, kwargs=kwargs)
            setattr(func, attribute, thread)
            thread.start()

        return func

    return decorator


setattr(threaded, "results", [])


def reset_current_job():
    if not XSH.shell:
        return

    prompt_fields = XSH.env["PROMPT_FIELDS"]
    with prompt_fields["current_job"].update_current_cmds([["xonsh"]]):
        prompt_fields.reset_key("current_job")
        XSH.shell.settitle()
