"""Duration-based selection policy for the repository's fast pytest gate.

The policy stays independent of pytest so unit tests and the root conftest share one
small, deterministic classifier.  Duration data is an intentionally conservative,
versioned JSON artifact: absent observations do not admit unmeasured tests to the
fast gate.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

DURATION_FILE_VERSION = 1


def is_slow(
    nodeid: str,
    duration: float | None,
    threshold: float,
    has_slow_marker: bool,
) -> bool:
    """Return whether a test belongs outside the fast gate."""
    del nodeid
    # Unknown tests must stay out of the commit-time gate until measured; a false
    # negative would silently make the gate slower for every contributor.
    return has_slow_marker or duration is None or duration >= threshold


def load_durations(path: Path) -> dict[str, float]:
    """Load duration observations from ``path``, returning none when it is absent."""
    if not path.exists():
        return {}

    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid duration JSON in {path}: {error}") from error

    if not isinstance(payload, dict):
        raise ValueError(f"Invalid duration file {path}: expected an object")
    version = payload.get("version")
    if type(version) is not int or version != DURATION_FILE_VERSION:
        raise ValueError(f"Unsupported duration file version in {path}: {version!r}")

    durations = payload.get("durations")
    if not isinstance(durations, dict):
        raise ValueError(f"Invalid duration file {path}: expected a durations object")

    parsed: dict[str, float] = {}
    for nodeid, duration in durations.items():
        if not isinstance(nodeid, str):
            raise ValueError(f"Invalid duration file {path}: node IDs must be strings")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise ValueError(
                f"Invalid duration for {nodeid!r} in {path}: expected a number"
            )
        if not math.isfinite(duration) or duration < 0:
            raise ValueError(
                f"Invalid duration for {nodeid!r} in {path}: expected a finite value "
                "greater than or equal to zero"
            )
        parsed[nodeid] = float(duration)

    return parsed
