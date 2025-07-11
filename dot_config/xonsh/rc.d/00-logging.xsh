import logging
from typing import Any


$LOG_LEVEL = logging.INFO
root_logger = logging.getLogger()

logging.basicConfig(level=$LOG_LEVEL)


@events.on_envvar_change
def _set_log_level(name: str, oldvalue: Any, newvalue: Any) -> None:
    if name != "LOG_LEVEL":
        return

    root_logger.setLevel(
        level=getattr(logging, newvalue.upper()) if isinstance(newvalue, str) else newvalue,
    )
