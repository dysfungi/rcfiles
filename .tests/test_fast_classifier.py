"""Regression coverage for duration-based fast-test selection.

The direct cases lock down the conservative classification boundary.  The pytester
case copies the production conftest and classifier into an isolated pytest project so
it exercises the user-facing ``--fast`` deselection workflow without this repository's
collection side effects.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from _fast_classify import is_slow, load_durations

pytest_plugins = ["pytester"]


@pytest.mark.parametrize(
    ("duration", "threshold", "has_slow_marker", "expected"),
    [
        (0.01, 0.2, True, True),
        (0.2, 0.2, False, True),
        (0.19, 0.2, False, False),
        (None, 0.2, False, True),
        (0.05, 0.05, False, True),
    ],
    ids=[
        "explicit-marker",
        "at-threshold",
        "below-threshold",
        "unknown",
        "custom-threshold",
    ],
)
def test_is_slow(
    duration: float | None,
    threshold: float,
    has_slow_marker: bool,
    expected: bool,
) -> None:
    """Classify explicit, measured, and unknown test durations."""
    assert (
        is_slow(
            ".tests/test_example.py::test_example",
            duration,
            threshold,
            has_slow_marker,
        )
        is expected
    )


def test_load_durations_rejects_malformed_json(tmp_path: Path) -> None:
    """Malformed persisted measurements fail instead of silently selecting tests."""
    duration_file = tmp_path / "durations.json"
    duration_file.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid duration JSON"):
        load_durations(duration_file)


@pytest.mark.parametrize("version", [True, 1.0], ids=["boolean", "float"])
def test_load_durations_rejects_non_integer_version(
    tmp_path: Path, version: bool | float
) -> None:
    """Only an exact integer format version is accepted."""
    duration_file = tmp_path / "durations.json"
    duration_file.write_text(
        json.dumps({"version": version, "durations": {}}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Unsupported duration file version"):
        load_durations(duration_file)


def test_store_durations_reloads_before_merging(tmp_path: Path) -> None:
    """The writer preserves measurements added after this session began."""
    duration_file = tmp_path / "durations.json"
    duration_file.write_text(
        json.dumps({"version": 1, "durations": {"test_a": 1.0}}),
        encoding="utf-8",
    )

    repository_root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "_root_fast_classifier_conftest", repository_root / "conftest.py"
    )
    assert spec is not None and spec.loader is not None
    duration_writer: Any = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = duration_writer
    spec.loader.exec_module(duration_writer)

    duration_writer._write_durations(
        duration_file, duration_writer._DurationRecorder(observed={"test_b": 2.0})
    )

    assert load_durations(duration_file) == {"test_a": 1.0, "test_b": 2.0}


def test_fast_deselects_slow_unknown_and_marked_tests(
    pytester: pytest.Pytester,
) -> None:
    """The production hook runs only a measured, unmarked fast test."""
    repository_root = Path(__file__).resolve().parents[1]
    pytester.makeconftest((repository_root / "conftest.py").read_text(encoding="utf-8"))
    classifier_directory = pytester.path / ".tests"
    classifier_directory.mkdir()
    (classifier_directory / "_fast_classify.py").write_text(
        (repository_root / ".tests" / "_fast_classify.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    pytester.makeini("""
        [pytest]
        markers =
            slow: manual slow-test override
    """)
    pytester.makepyfile(
        test_selection="""
            import pytest

            def test_fast():
                pass

            def test_unknown():
                pass

            @pytest.mark.slow
            def test_marked_slow():
                pass
        """
    )
    pytester.makefile(
        ".json",
        durations=json.dumps(
            {
                "durations": {"test_selection.py::test_fast": 0.1},
                "version": 1,
            },
            sort_keys=True,
        ),
    )

    result = pytester.runpytest("--fast", "--duration-file=durations.json", "-q")

    result.assert_outcomes(passed=1, deselected=2)


@pytest.mark.parametrize("threshold", ["nan", "inf", "-0.1"])
def test_slow_threshold_rejects_invalid_values(
    pytester: pytest.Pytester, threshold: str
) -> None:
    """Non-finite and negative thresholds cannot weaken fast-test selection."""
    repository_root = Path(__file__).resolve().parents[1]
    pytester.makeconftest((repository_root / "conftest.py").read_text(encoding="utf-8"))
    classifier_directory = pytester.path / ".tests"
    classifier_directory.mkdir()
    (classifier_directory / "_fast_classify.py").write_text(
        (repository_root / ".tests" / "_fast_classify.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = pytester.runpytest(f"--slow-threshold={threshold}")

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(
        ["*--slow-threshold must be finite and greater than or equal to zero*"]
    )


def test_store_durations_omits_skipped_tests(pytester: pytest.Pytester) -> None:
    """Quarantined tests do not acquire a duration from their skip setup report."""
    repository_root = Path(__file__).resolve().parents[1]
    pytester.makeconftest((repository_root / "conftest.py").read_text(encoding="utf-8"))
    classifier_directory = pytester.path / ".tests"
    classifier_directory.mkdir()
    (classifier_directory / "_fast_classify.py").write_text(
        (repository_root / ".tests" / "_fast_classify.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    pytester.makepyfile(
        test_recording="""
            import pytest

            def test_measured():
                pass

            @pytest.mark.skip(reason="quarantined")
            def test_skipped():
                pass
        """
    )

    duration_file = pytester.path / "durations.json"
    duration_file.write_text(
        json.dumps(
            {
                "durations": {"test_recording.py::test_skipped": 1.0},
                "version": 1,
            }
        ),
        encoding="utf-8",
    )

    result = pytester.runpytest(
        "--store-durations", "--duration-file=durations.json", "-q"
    )

    result.assert_outcomes(passed=1, skipped=1)
    durations = json.loads(duration_file.read_text())
    assert durations["durations"].keys() == {"test_recording.py::test_measured"}
