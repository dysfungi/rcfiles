"""Pytest hooks for duration-based fast-test selection and measurement.

The root conftest owns pytest integration while ``.tests/_fast_classify.py`` owns the
pure policy.  Keeping the policy importable lets its regression tests exercise the
same behavior without depending on pytest's conftest discovery.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest

try:
    import fcntl
except ImportError:
    fcntl = None

_TESTS_DIRECTORY = Path(__file__).with_name(".tests")
_classifier_spec = importlib.util.spec_from_file_location(
    "_fast_classify", _TESTS_DIRECTORY / "_fast_classify.py"
)
if _classifier_spec is None or _classifier_spec.loader is None:
    raise RuntimeError("Unable to load the fast-test classifier")
_classifier = importlib.util.module_from_spec(_classifier_spec)
sys.modules[_classifier_spec.name] = _classifier
_classifier_spec.loader.exec_module(_classifier)

DURATION_FILE_VERSION = _classifier.DURATION_FILE_VERSION
is_slow = _classifier.is_slow
load_durations = _classifier.load_durations


@dataclass
class _DurationRecorder:
    """Duration data collected for one successful pytest session."""

    observed: dict[str, float] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)


_duration_recorder: _DurationRecorder | None = None


def _duration_file(config: pytest.Config) -> Path:
    configured_path = Path(config.getoption("duration_file"))
    if configured_path.is_absolute():
        return configured_path
    return Path(config.rootpath) / configured_path


def _parse_slow_threshold(value: str) -> float:
    """Parse a threshold that can safely classify measured test durations."""
    threshold = float(value)
    if not math.isfinite(threshold) or threshold < 0:
        raise pytest.UsageError(
            "--slow-threshold must be finite and greater than or equal to zero"
        )
    return threshold


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register duration-classification controls."""
    group = parser.getgroup("fast tests")
    group.addoption(
        "--fast",
        action="store_true",
        help="Run only tests with a measured duration below --slow-threshold.",
    )
    group.addoption(
        "--slow-threshold",
        type=_parse_slow_threshold,
        default=0.2,
        help="Classify tests at or above this duration in seconds as slow (default: 0.2).",
    )
    group.addoption(
        "--duration-file",
        default=".test_durations",
        help="Duration JSON path, relative to pytest's root directory by default.",
    )
    group.addoption(
        "--store-durations",
        action="store_true",
        help="Atomically merge full test protocol durations into --duration-file.",
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    """Validate persisted data before optional duration recording begins."""
    global _duration_recorder
    if not session.config.getoption("store_durations"):
        _duration_recorder = None
        return

    load_durations(_duration_file(session.config))
    _duration_recorder = _DurationRecorder()


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Deselect slow and unmeasured tests when the fast gate is requested."""
    if not config.getoption("fast"):
        return

    durations = load_durations(_duration_file(config))
    threshold = config.getoption("slow_threshold")
    fast_items: list[pytest.Item] = []
    slow_items: list[pytest.Item] = []

    for item in items:
        if is_slow(
            item.nodeid,
            durations.get(item.nodeid),
            threshold,
            item.get_closest_marker("slow") is not None,
        ):
            slow_items.append(item)
        else:
            fast_items.append(item)

    if slow_items:
        config.hook.pytest_deselected(items=slow_items)
    items[:] = fast_items


# Keep --fail-slow on the --fast command only: full validation intentionally includes
# integration tests whose expected runtime exceeds the fast gate's regression budget.
def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Accumulate setup, call, and teardown time for each test protocol."""
    if _duration_recorder is None:
        return
    if report.outcome == "skipped":
        # Skipped tests intentionally have no runtime budget and must not persist a
        # setup-report duration that would classify them after their quarantine ends.
        _duration_recorder.skipped.add(report.nodeid)
        _duration_recorder.observed.pop(report.nodeid, None)
        return
    if report.when not in {"setup", "call", "teardown"}:
        return

    _duration_recorder.observed[report.nodeid] = (
        _duration_recorder.observed.get(report.nodeid, 0.0) + report.duration
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Persist conservative measurements after a completely successful session."""
    global _duration_recorder
    recorder = _duration_recorder
    _duration_recorder = None

    if recorder is None or exitstatus != pytest.ExitCode.OK:
        return

    _write_durations(_duration_file(session.config), recorder)


def _write_durations(duration_file: Path, recorder: _DurationRecorder) -> None:
    """Merge one successful session's measurements into the duration file."""
    duration_file.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:
        _merge_and_write_durations(duration_file, recorder)
        return

    lock_path = duration_file.with_name(f"{duration_file.name}.lock")
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            _merge_and_write_durations(duration_file, recorder)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _merge_and_write_durations(
    duration_file: Path, recorder: _DurationRecorder
) -> None:
    """Reload, max-merge, and atomically replace a duration file."""
    durations = load_durations(duration_file)
    for nodeid in recorder.skipped:
        durations.pop(nodeid, None)
    for nodeid, observed in recorder.observed.items():
        if nodeid not in recorder.skipped:
            durations[nodeid] = max(durations.get(nodeid, 0.0), observed)

    payload = {"version": DURATION_FILE_VERSION, "durations": durations}
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=duration_file.parent,
            prefix=f".{duration_file.name}.",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(payload, temporary_file, indent=2, sort_keys=True)
            temporary_file.write("\n")
        os.replace(temporary_path, duration_file)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
