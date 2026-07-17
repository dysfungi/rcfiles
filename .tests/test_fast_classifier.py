"""Regression coverage for duration-based fast-test selection.

The direct cases lock down the conservative classification boundary.  The pytester
case copies the production conftest and classifier into an isolated pytest project so
it exercises the user-facing ``--fast`` deselection workflow without this repository's
collection side effects.
"""

from __future__ import annotations

import json
from pathlib import Path

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
